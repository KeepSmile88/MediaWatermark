#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import time

from PySide6.QtCore import Signal, QThread


class WorkerThread(QThread):
    progress = Signal(int)
    max_progress = Signal(int)
    completed = Signal(object)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def stop(self):
        self._stop_flag = True
        self.quit()
        self.wait()

    def run(self):
        result = self.func(*self.args, **self.kwargs)
        self.completed.emit(result)


class MonitorThread(QThread):
    completed = Signal(str)

    def __init__(self, workers):
        super().__init__()
        self.workers = workers
        self._stop_flag = False
        self._completed_flag = False

    def run(self):
        while not self._stop_flag:
            time.sleep(1)

            # 移除已完成的线程，避免重复检查
            self.workers = [worker for worker in self.workers if worker.isRunning()]
            print(f"剩余线程数：{len(self.workers)}")

            if not self.workers and not self._completed_flag:  # 所有线程都已完成
                self._completed_flag = True
                self._stop_flag = True
                print("所有线程都已完成.")
                time.sleep(1)
                self.completed.emit("end")

    def stop(self):
        self._stop_flag = True

    def remove_worker(self, worker):
        if worker in self.workers:
            print("移除线程：\t", worker)
            self.workers.remove(worker)
