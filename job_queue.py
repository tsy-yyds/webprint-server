# -*- coding: utf-8 -*-
"""
打印任务队列：后台单线程串行打印，避免多任务同时打同一台打印机。
任务状态：
    queued -> printing -> done / failed
    手动双面：printing -> waiting（等待翻面确认）-> printing -> done
    取消：waiting / queued 时调用 cancel -> cancelled
"""
import os
import queue
import re
import threading
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _sanitize(name):
    name = Path(name).name
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    name = name.strip() or 'file'
    return name[:120]


class JobManager:
    def __init__(self, jobs_dir, print_fn=None, render_fn=None, export_fn=None,
                 exports_dir=None, quality_map=None, keep_days=7, log=None):
        """
        print_fn(images, printer_name, options) -> (pages, copies)
        render_fn(path, dpi) -> list[PIL.Image]
        export_fn(src_path, out_pdf_path) -> None（把文件转成 PDF）
        exports_dir: 打印到 PDF 的输出目录
        """
        self.jobs_dir = Path(jobs_dir)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir = Path(exports_dir) if exports_dir else None
        self.print_fn = print_fn
        self.render_fn = render_fn
        self.export_fn = export_fn
        self.quality_map = quality_map or {'draft': 150, 'standard': 200, 'high': 300}
        self.keep_days = keep_days
        self.log = log or (lambda msg: None)

        self.jobs = {}
        self.lock = threading.Lock()
        self.print_lock = threading.Lock()
        self._queue = queue.Queue()
        self._worker_started = False
        self._wait_events = {}  # jid -> threading.Event（手动双面等待翻面）

    # ---------- 任务管理 ----------
    def create(self, files, options):
        jid = uuid.uuid4().hex[:10]
        jdir = self.jobs_dir / jid
        in_dir = jdir / 'in'
        in_dir.mkdir(parents=True, exist_ok=True)

        names = []
        for f in files:
            fname = _sanitize(f.filename or '')
            save_path = in_dir / fname
            if save_path.exists():
                save_path = in_dir / ('%s_%s' % (jid, fname))
            f.save(str(save_path))
            names.append(save_path.name)

        job = {
            'id': jid,
            'created': _now(),
            'status': 'queued',
            'files': names,
            'options': dict(options),
            'pages': 0,
            'copies': 0,
            'phase': 0,       # 手动双面：当前已完成第几趟（0 = 未开始）
            'phases': 1,      # 总趟数（手动双面 = 2）
            'output_pdf': '',  # 打印到 PDF 时输出文件名
            'error': '',
            'finished': None,
            'dir': str(jdir),
        }
        with self.lock:
            self.jobs[jid] = job
        self._enqueue(jid)
        self._cleanup_old()
        return job

    def get(self, jid):
        with self.lock:
            return self.jobs.get(jid)

    def list(self, limit=50):
        with self.lock:
            items = sorted(self.jobs.values(), key=lambda j: j['created'], reverse=True)
            return items[:limit]

    # ---------- 队列 ----------
    def _enqueue(self, jid):
        if not self._worker_started:
            self._worker_started = True
            t = threading.Thread(target=self._run, daemon=True, name='print-worker')
            t.start()
        self._queue.put(jid)

    def _run(self):
        while True:
            jid = self._queue.get()
            try:
                self._process(jid)
            except Exception:
                job = self.get(jid)
                if job:
                    job['status'] = 'failed'
                    job['error'] = '内部错误：%s' % traceback.format_exc(limit=2)[-500:]
                    job['finished'] = _now()
                self.log('job %s 处理异常: %s' % (jid, traceback.format_exc()))
            finally:
                self._queue.task_done()

    # ---------- 手动双面：继续 / 取消 ----------
    def continue_job(self, jid):
        """手动双面：用户确认已翻面放回，继续打印背面"""
        job = self.get(jid)
        if not job:
            return False, '任务不存在'
        if job['status'] != 'waiting':
            return False, '任务不在等待翻面状态'
        job['status'] = 'printing'
        ev = self._wait_events.get(jid)
        if ev:
            ev.set()
        self.log('[%s] 用户确认翻面，继续打印背面' % jid)
        return True, ''

    def cancel_job(self, jid):
        """取消任务：仅 queued / waiting 状态可取消"""
        job = self.get(jid)
        if not job:
            return False, '任务不存在'
        if job['status'] in ('done', 'failed', 'cancelled'):
            return False, '任务已完成，无法取消'
        job['cancelled'] = True
        if job['status'] == 'waiting':
            ev = self._wait_events.get(jid)
            if ev:
                ev.set()
        elif job['status'] == 'queued':
            job['status'] = 'cancelled'
            job['finished'] = _now()
        self.log('[%s] 任务已取消' % jid)
        return True, ''

    # ---------- 处理 ----------
    def _render_images(self, job):
        q = job['options'].get('quality', 'standard')
        dpi = int(self.quality_map.get(q, 200))
        images = []
        for name in job['files']:
            path = Path(job['dir']) / 'in' / name
            images.extend(self.render_fn(str(path), dpi=dpi))
        if not images:
            raise RuntimeError('文件渲染后没有可打印的内容')
        return images

    def _export_pdf(self, job):
        """打印到 PDF：把每个文件转成 PDF，合并后存入导出目录，返回文件名"""
        if not self.export_fn or not self.exports_dir:
            raise RuntimeError('服务器未启用 PDF 输出功能')
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        first = job['files'][0] if job['files'] else '打印'
        base = re.sub(r'[^\w\u4e00-\u9fff-]', '', Path(first).stem)[:40] or '打印'
        out_name = '%s_%s.pdf' % (base, time.strftime('%Y%m%d_%H%M%S'))
        out_path = self.exports_dir / out_name

        tmps = []
        try:
            for name in job['files']:
                src = Path(job['dir']) / 'in' / name
                tmp = self.exports_dir / ('_tmp_%s_%s' % (job['id'], name))
                self.export_fn(str(src), str(tmp))
                tmps.append(str(tmp))
            if len(tmps) == 1:
                os.replace(tmps[0], str(out_path))
                tmps = []
            else:
                from file_render import merge_pdfs
                merge_pdfs(tmps, str(out_path))
        finally:
            for t in tmps:
                try:
                    os.remove(t)
                except Exception:
                    pass
        return out_name

    def _process(self, jid):
        job = self.get(jid)
        if not job:
            return
        if job.get('cancelled'):
            job['status'] = 'cancelled'
            job['finished'] = _now()
            return

        # ---- 打印到 PDF：不进打印队列，直接转换保存 ----
        if job['options'].get('to_pdf'):
            job['status'] = 'printing'
            self.log('[%s] 开始转换为 PDF：%s' % (jid, ','.join(job['files'])))
            try:
                job['output_pdf'] = self._export_pdf(job)
                job['pages'] = 1
                job['copies'] = 1
                job['status'] = 'done'
                self.log('[%s] PDF 已生成：%s' % (jid, job['output_pdf']))
            except Exception as e:
                job['status'] = 'failed'
                job['error'] = str(e)
                self.log('[%s] PDF 转换失败：%s' % (jid, e))
            finally:
                job['finished'] = _now()
            return

        # ---- 打印到纸 ----
        job['status'] = 'printing'
        self.log('[%s] 开始打印 %s' % (jid, ','.join(job['files'])))
        try:
            images = self._render_images(job)
            opts = dict(job['options'])

            # 手动双面：拆成两趟（奇数页 -> 翻面 -> 偶数页倒序）
            if opts.get('duplex') == 'manual':
                opts['duplex'] = 'simplex'   # 驱动层始终单面，由队列拆两趟
                opts['copies'] = 1            # 手动双面只支持 1 份
                phases = [images[0::2], images[1::2][::-1]]
            else:
                phases = [images]
            job['phases'] = len(phases)
            job['phase'] = 0

            total_pages = 0
            copies = 1
            for i, phase in enumerate(phases):
                if job.get('cancelled'):
                    break
                with self.print_lock:
                    pages, copies = self.print_fn(phase, opts.get('printer', ''), opts)
                total_pages += pages
                job['phase'] = i + 1

                if i < len(phases) - 1:
                    # 第一趟完成，等待用户翻面确认（阻塞队列，后续任务排队）
                    job['status'] = 'waiting'
                    job['pages'] = total_pages   # 让前端弹窗能显示第 1 面页数
                    self.log('[%s] 手动双面：第 1 面完成（%d 页），等待翻面确认' % (jid, pages))
                    ev = threading.Event()
                    self._wait_events[jid] = ev
                    try:
                        ev.wait()
                    finally:
                        self._wait_events.pop(jid, None)
                    if job.get('cancelled'):
                        break
                    job['status'] = 'printing'
                    self.log('[%s] 手动双面：开始打印背面（%d 页）' % (jid, len(phases[i + 1])))

            if job.get('cancelled'):
                job['status'] = 'cancelled'
                self.log('[%s] 手动双面已取消' % jid)
            else:
                job['pages'] = total_pages
                job['copies'] = copies
                job['status'] = 'done'
                self.log('[%s] 完成：%d 页 x %d 份（%d 趟）' % (jid, total_pages, copies, job['phases']))
        except Exception as e:
            job['status'] = 'failed'
            job['error'] = str(e)
            job['finished'] = _now()
            self.log('[%s] 失败：%s' % (jid, e))
        finally:
            if job['status'] in ('done', 'failed', 'cancelled'):
                job['finished'] = _now()

    # ---------- 清理 ----------
    def _cleanup_old(self):
        try:
            now = time.time()
            for jid in list(self.jobs.keys()):
                job = self.jobs.get(jid)
                if not job:
                    continue
                if job['finished']:
                    try:
                        ft = datetime.strptime(job['finished'], '%Y-%m-%d %H:%M:%S').timestamp()
                    except Exception:
                        continue
                    if now - ft > self.keep_days * 86400:
                        try:
                            import shutil
                            shutil.rmtree(job['dir'], ignore_errors=True)
                        except Exception:
                            pass
                        self.jobs.pop(jid, None)
        except Exception:
            pass
