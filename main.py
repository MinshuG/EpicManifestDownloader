import multiprocessing
import os
import sys
import logging

from PyQt6.QtCore import QThread, pyqtSignal, QObject
from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QLineEdit, QPushButton, QFileDialog, QHBoxLayout, QVBoxLayout, QProgressBar, QTextEdit
from legendary.models.manifest import Manifest
from legendary.models.json_manifest import JSONManifest
from legendary.downloader.mp.manager import DLManager
from legendary.models.downloading import UIUpdate

class WorkInfo:
    BaseUrl: str
    Manifest: str
    DownloadLocation: str


class ThisWorksSoo:
    def __init__(self, callback):
        self.callback = callback

    def put(self, item, timeout=None):
        self.callback(item)

class DownloadThread(QThread):
    progress_signal = pyqtSignal(float, float, float, float)
    
    def __init__(self, url, work: WorkInfo):
        QThread.__init__(self)
        self.url = url
        self.work = work
        self.progress_queue = ThisWorksSoo(self.update_progress)
        self.manager = DLManager(self.work.DownloadLocation, self.work.BaseUrl, os.path.join(self.work.DownloadLocation, ".cache"), self.progress_queue, resume_file=os.path.join(self.work.DownloadLocation, ".resumedata"))
        # breakpoint()

    def run(self):
        # download_result = download_file(self.url, self.dest_file, progress_callback=self.update_progress)
        with open(self.work.Manifest, "rb") as f:
            data = f.read()
            try:
                manifest = Manifest.read_all(data)
            except Exception as e:
                manifest = JSONManifest.read_all(data)

        self.manager.run_analysis(manifest, None, processing_optimization=False)
        
        try:
            self.manager.run()
            # exec("downloader.run()", globals(), locals())
        except SystemExit as e:
            pass
        self.finished.emit()
    
    def update_progress(self, progress: UIUpdate):
        if progress:
            mbs = progress.download_speed / 1024 / 1024
            self.progress_signal.emit(progress.progress, mbs, progress.read_speed/1024/1024, progress.write_speed/1024/1024)

    def kill(self):
        import signal
        os.kill(self.manager._parent_pid, signal.SIGTERM)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.url_label = QLabel("BaseURL:")
        self.url_edit = QLineEdit()
        self.url_edit.setText("https://epicgames-download1.akamaized.net/Builds/Fortnite/CloudDir/")
        self.manifest_picker_button = QPushButton("Select Manifest...")
        self.manifest_location_label = QLabel("Manifest Location:")
        self.manifest_location_edit = QLineEdit()
        self.download_location_label = QLabel("Download Location:")
        self.download_location_edit = QLineEdit()
        self.download_location_button = QPushButton("Browse...")
        self.download_button = QPushButton("Download")
        self.progress_bar = QProgressBar()
        self.progress_label = QLabel()
        self.speed_label = QLabel()
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.download_thread = None
        
        self.manifest_picker_button.clicked.connect(self.select_manifest)
        self.download_location_button.clicked.connect(self.browse_download_location)
        self.download_button.clicked.connect(self.download_file)
        
        input_layout = QVBoxLayout()
        input_layout.addWidget(self.url_label)
        input_layout.addWidget(self.url_edit)


        # manifest location
        input_layout.addWidget(self.manifest_location_label)
        manifest_layout = QHBoxLayout()
        manifest_layout.addWidget(self.manifest_location_edit)
        manifest_layout.addWidget(self.manifest_picker_button)
        input_layout.addLayout(manifest_layout)
        
        # download location
        input_layout.addWidget(self.download_location_label)
        download_layout = QHBoxLayout()
        download_layout.addWidget(self.download_location_edit)
        download_layout.addWidget(self.download_location_button)
        input_layout.addLayout(download_layout)

        # download button
        input_layout.addWidget(self.download_button)

        progress_layout = QVBoxLayout()
        progress_layout.addWidget(self.progress_label)
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.speed_label)
        
        console_layout = QVBoxLayout()
        console_layout.addWidget(QLabel("Console Output:"))
        console_layout.addWidget(self.console)

        main_layout = QVBoxLayout()
        main_layout.addLayout(input_layout)
        main_layout.addLayout(progress_layout)
        main_layout.addLayout(console_layout)

        
        self.setLayout(main_layout)
        self.setup_stdout_hijack()
        
        self.setGeometry(100, 100, 500, 390)
        self.setWindowTitle("Epic Manifest Downloader")
        self.show()
    
    def select_manifest(self):
        manifest_path, _ = QFileDialog.getOpenFileName(self, "Select Manifest to Download")
        self.manifest_location_edit.setText(manifest_path)
        logging.getLogger().info(f"Selected manifest: {manifest_path}")
        
    def browse_download_location(self):
        download_dir = QFileDialog.getExistingDirectory(self, "Choose Download Directory")
        self.download_location_edit.setText(download_dir)

    def download_file(self):
        url = self.url_edit.text()
        manifest_path = self.manifest_location_edit.text()
        dest_dir = self.download_location_edit.text()
        
        work = WorkInfo()
        work.BaseUrl = url
        work.Manifest = manifest_path
        work.DownloadLocation = dest_dir
        
        self.download_thread = DownloadThread(url, work)
        self.download_thread.progress_signal.connect(self.update_progress)
        self.download_thread.start()
        # disable download button
        self.download_button.setEnabled(False)
        
    def update_progress(self, progress_percent, speed, read_speed, write_speed):
        self.progress_bar.setValue(int(progress_percent))
        self.speed_label.setText(f"Download {speed:.2f} MB/s")
        self.progress_label.setText(f"R/W {read_speed:.2f} MB/s, {write_speed:.2f} MB/s")
        # self.console.append(f"{filename} - {progress_percent:.2f}%")

    def write_to_console(self, text: str):
        text = text[:-1] if text.endswith("\n") else text
        self.console.append(text)

    def setup_stdout_hijack(self):
        # setup logger
        stream = LoggerStream()
        stream.newText.connect(self.write_to_console)

        logging.basicConfig(level=logging.INFO)
        logging.getLogger
        dlm = logging.getLogger("DLM")
        dlm.setLevel(logging.INFO)

        logging.getLogger().addHandler(logging.StreamHandler(stream))
    
    def closeEvent(self, a0) -> None:
        if self.download_thread:
            self.download_thread.manager.running = False
            self.download_thread.kill()
        return super().closeEvent(a0)


class LoggerStream(QObject):
    newText = pyqtSignal(str)

    def write(self, text):
        self.newText.emit(str(text))

    def flush(self):
        pass

if __name__ == '__main__':
    multiprocessing.freeze_support()
    app = QApplication([])
    window = MainWindow()
    sys.exit(app.exec())
