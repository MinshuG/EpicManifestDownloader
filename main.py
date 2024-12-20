import multiprocessing
import os
import sys
import logging
import re
import queue
from multiprocessing import Queue as MPQueue
from logging.handlers import QueueListener


from PyQt6.QtCore import QThread, pyqtSignal, QObject, Qt
from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QLineEdit, QPushButton, QFileDialog, QHBoxLayout, QVBoxLayout, QProgressBar, QTextEdit
from PyQt6.QtWidgets import *
from legendary.models.manifest import Manifest
from legendary.models.json_manifest import JSONManifest
from legendary.downloader.mp.manager import DLManager
from legendary.models.downloading import UIUpdate, FileTask, TaskFlags

class WorkInfo:
    BaseUrl: str
    Manifest: str
    DownloadLocation: str
    install_tags: list[str]


class ThisWorksSoo:
    def __init__(self, callback):
        self.callback = callback

    def put(self, item, timeout=None):
        self.callback(item)

url_regex = "^https?:\\/\\/(?:www\\.)?[-a-zA-Z0-9@:%._\\+~#=]{1,256}\\.[a-zA-Z0-9()]{1,6}\\b(?:[-a-zA-Z0-9()@:%_\\+.~#?&\\/=]*)$"

class DownloadThread(QThread):
    progress_signal = pyqtSignal(float, float, float, float)
     
    def setup_threaded_logging(self):
        self.logging_queue = MPQueue(-1)

        shandler = logging.getLogger().handlers[0]
        ql = QueueListener(self.logging_queue, shandler)
        ql.start()
        return ql

    def __init__(self, url, work: WorkInfo):
        QThread.__init__(self)
        self.url = url
        self.work = work
        status_queue = MPQueue()
        # self.progress_queue = ThisWorksSoo(self.update_progress)
        self.manager = DLManager(self.work.DownloadLocation, self.work.BaseUrl, os.path.join(self.work.DownloadLocation, ".cache"), status_queue, resume_file=os.path.join(self.work.DownloadLocation, ".resumedata"))
        self.setup_threaded_logging()
        self.manager.logging_queue = self.logging_queue

        is_url = re.match(url_regex, self.work.Manifest)
        logging.getLogger().info("Manifest URL Detected." if is_url else "")

    def run(self):
        if len(self.work.install_tags) > 0:
            logging.getLogger().info(f"Filtering files with tags: {self.work.install_tags}")
        # else:
        #     logging.getLogger().info("No tags specified. Downloading all files.")
        #     self.work.install_tags = None

        manifest = self.get_manifest(self.work.Manifest)
        if not manifest:
            return
        tags = [""] # empty tag for necessary files
        tags.extend(self.work.install_tags)

        analysis = self.manager.run_analysis(manifest, None, processing_optimization=True, file_install_tag=tags)

        # prevent deletion of files
        tasks = []
        for task in self.manager.tasks:
            # remove delete tasks
            if isinstance(task, FileTask) and task.flags & TaskFlags.DELETE_FILE:
                continue
            tasks.append(task)

        self.manager.tasks.clear()
        self.manager.tasks.extend(tasks)

        logging.getLogger().info("Starting download...")
        # try:
        self.manager.start()

        while self.manager.is_alive():
            try:
                self.update_progress(self.manager.status_queue.get(timeout=1.0))
            except queue.Empty:
                pass
        # except Exception as e:
        #     logging.getLogger().error(f"Download Failed:")
        #     logging.getLogger().error(f"Error: {e}")
        #     # self.manager.join()
        #     self.kill()
        # else:
        #     logging.getLogger().info("Download Finished.")

        self.finished.emit()

    @staticmethod
    def run_download(manager):
        manager.start()
        # manager.join()

    @staticmethod
    def get_manifest(manifest):
        is_url = re.match(url_regex, manifest)
        # download_result = download_file(self.url, self.dest_file, progress_callback=self.update_progress)
        if is_url:
            logging.getLogger().info("Downloading manifest from URL...")
            import requests
            resp = requests.get(manifest, stream=True)
            data = resp.content
        else:
            if not os.path.exists(manifest):
                logging.getLogger().error(f"Manifest file not found: {manifest}")
                return None
            f =  open(manifest, "rb")
            data = f.read()
        try:
            try:
                manifest = Manifest.read_all(data)
            except Exception as e:
                manifest = JSONManifest.read_all(data)
        except Exception as e:
            logging.getLogger().error(f"Failed to read manifest. Corrupted file?")
            # logging.getLogger().error(f"Error: {e}")
            return None
        return manifest
    
    def update_progress(self, progress: UIUpdate):
        print(progress)
        if progress:
            mbs = progress.download_speed / 1024 / 1024
            self.progress_signal.emit(progress.progress, mbs, progress.read_speed/1024/1024, progress.write_speed/1024/1024)
    
    def kill(self):
        self.manager.running = False
        self.manager.kill()
        self.manager.join()


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.url_label = QLabel("BaseURL:")
        self.url_edit = QLineEdit()
        self.url_edit.setText("https://epicgames-download1.akamaized.net/Builds/Fortnite/CloudDir/")
        self.manifest_picker_button = QPushButton("Browse")
        self.manifest_location_label = QLabel("Manifest Location/URL:")
        self.manifest_location_edit = QLineEdit()
        self.install_tags_list = QListWidget()
        self.all_tags_list = QListWidget()
        self.add_tag_button = QPushButton("Add ->")
        self.remove_tag_button = QPushButton("<- Remove")
        self.download_location_label = QLabel("Download Location:")
        self.download_location_edit = QLineEdit()
        self.download_location_button = QPushButton("Browse")
        self.download_button = QPushButton("Download")
        self.progress_bar = QProgressBar()
        self.progress_label = QLabel()
        self.speed_label = QLabel()
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.download_thread = None
        
        self.manifest_picker_button.clicked.connect(self.select_manifest)
        self.manifest_location_edit.textChanged.connect(self.manifest_path_changed)
        self.download_location_button.clicked.connect(self.browse_download_location)
        self.download_button.clicked.connect(self.download_file)
        self.add_tag_button.clicked.connect(self.add_install_tag)
        self.remove_tag_button.clicked.connect(self.remove_install_tag)
        self.install_tags_list.doubleClicked.connect(self.remove_install_tag)
        self.all_tags_list.doubleClicked.connect(self.add_install_tag)

        input_layout = QVBoxLayout()
        input_layout.addWidget(self.url_label)
        input_layout.addWidget(self.url_edit)


        # manifest location
        input_layout.addWidget(self.manifest_location_label)
        manifest_layout = QHBoxLayout()
        manifest_layout.addWidget(self.manifest_location_edit)
        manifest_layout.addWidget(self.manifest_picker_button)
        input_layout.addLayout(manifest_layout)

        install_layout = QHBoxLayout()
        selected_tags_layout = QVBoxLayout()
        selected_tags_layout.addWidget(QLabel("Install Tags:"))
        # list of files to install
        selected_tags_layout.addWidget(self.all_tags_list)
        install_layout.addLayout(selected_tags_layout)
        
        move_button_layout = QVBoxLayout()
        move_button_layout.addSpacing(20)
        move_button_layout.addWidget(self.add_tag_button, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        move_button_layout.addWidget(self.remove_tag_button, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        install_layout.addLayout(move_button_layout, 1)

        # list of files to skip
        all_tags_layout = QVBoxLayout()
        all_tags_layout.addWidget(QLabel("Tags to Install:"))
        all_tags_layout.addWidget(self.install_tags_list)
        install_layout.addLayout(all_tags_layout)

        input_layout.addLayout(install_layout)

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
        manifest_path, _ = QFileDialog.getOpenFileName(self, "Select Manifest")
        self.manifest_location_edit.setText(manifest_path)

    def manifest_path_changed(self):
        manifest_path = self.manifest_location_edit.text()
        logging.getLogger().info(f"Selected manifest: {manifest_path}")

        manifest = DownloadThread.get_manifest(manifest_path)
        if not manifest:
            self.download_button.setEnabled(False)
            return # invalid manifest
        else:
            self.download_button.setEnabled(True)

        self.install_tags_list.clear()
        self.all_tags_list.clear()
        tags = []
        for item in manifest.file_manifest_list.elements:
            tags.extend(item.install_tags)
        
        tags = list(set(tags))
        tags.sort()
        self.all_tags_list.addItems(tags)

    def add_install_tag(self):
        selected = self.all_tags_list.selectedItems()
        for item in selected:
            self.install_tags_list.addItem(item.text())
            self.all_tags_list.takeItem(self.all_tags_list.row(item))

    def remove_install_tag(self):
        selected = self.install_tags_list.selectedItems()
        for item in selected:
            self.all_tags_list.addItem(item.text())
            self.install_tags_list.takeItem(self.install_tags_list.row(item))
        
        # Sort the all_tags_list
        self.all_tags_list.sortItems()

    def browse_download_location(self):
        download_dir = QFileDialog.getExistingDirectory(self, "Choose Download Directory")
        self.download_location_edit.setText(download_dir)

    # start download
    def download_file(self):
        url = self.url_edit.text()
        manifest_path = self.manifest_location_edit.text()
        dest_dir = self.download_location_edit.text()
        
        work = WorkInfo()
        work.BaseUrl = url
        work.Manifest = manifest_path
        work.DownloadLocation = dest_dir
        work.install_tags = [self.install_tags_list.item(i).text() for i in range(self.install_tags_list.count())]

        self.download_thread = DownloadThread(url, work)
        self.download_thread.progress_signal.connect(self.update_progress)
        self.download_thread.finished.connect(self.download_finished)
        self.download_thread.start()
        # disable download button
        self.download_button.setEnabled(False)

    def update_progress(self, progress_percent, speed, read_speed, write_speed):
        self.progress_bar.setValue(int(progress_percent))
        self.speed_label.setText(f"Download {speed:.2f} MB/s")
        self.progress_label.setText(f"R/W {read_speed:.2f} MB/s, {write_speed:.2f} MB/s")
        # self.console.append(f"{filename} - {progress_percent:.2f}%")

    def download_finished(self):
        self.progress_label.setText("Cleaning up...")
        self.download_thread.manager.running = False # not tested
        self.download_thread.kill()

        self.download_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Download Finished")
        self.speed_label.setText("")

    def write_to_console(self, text: str):
        text = text[:-1] if text.endswith("\n") else text
        self.console.append(text)

    def setup_stdout_hijack(self):
        # setup logger
        stream = LoggerStream()
        stream.newText.connect(self.write_to_console)

        # sys.stdout = stream
        # sys.stderr = stream

        logging.basicConfig(level=logging.INFO, format='%(message)s')
        dlm = logging.getLogger("DLM")
        dlm.setLevel(logging.INFO)
        dlmm = logging.getLogger("DLManager")
        dlmm.setLevel(logging.INFO)

        handler = logging.StreamHandler(stream)
        
        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(handler)


    def closeEvent(self, a0) -> None:
        if self.download_thread:
            self.download_thread.kill()
        return super().closeEvent(a0)


class LoggerStream(QObject):
    newText = pyqtSignal(str)

    def write(self, text):
        self.newText.emit(str(text))

    def flush(self):
        pass


def main():
    app = QApplication([])
    window = MainWindow()
    sys.exit(app.exec())

def test_download():
    
    # class DummyLoggerStream():
    #     def write(self, text):
    #         print(text, end="")

    #     def flush(self):
    #         pass

    def slog():
    #     # stream = DummyLoggerStream()

    #     # sys.stdout = stream
    #     # sys.stderr = stream

    #     logging.basicConfig(level=logging.INFO)
    #     dlm = logging.getLogger("DLM")
    #     dlm.setLevel(logging.INFO)

        logging.getLogger().addHandler(logging.StreamHandler())

    slog()

    work = WorkInfo()
    work.BaseUrl = "https://epicgames-download1.akamaized.net/Builds/Fortnite/CloudDir"
    work.Manifest = r"https://github.com/polynite/fn-releases/raw/master/manifests/w0RPuFOxVVMSrBvizUa4g8PCYiRedw.manifest"
    work.DownloadLocation = r"F:\Fortnite Versions\19.10"
    work.install_tags = []
    thread = DownloadThread("https://epicgames-download1.akamaized.net/Builds/Fortnite/CloudDir/", work)
    thread.progress_signal.connect(lambda progress: print(progress))
    thread.start()
    while thread.isRunning():
        pass
    # thread.join()

if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
