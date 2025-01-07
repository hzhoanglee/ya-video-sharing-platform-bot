import subprocess
import re
import threading
import time

class RcloneUploader:
    def __init__(self, bot=None):
        self.bot = bot
        self.current_percentage = 0
        self.status_message = None
        self.is_uploading = False

    def parse_progress(self, line):
        match = re.search(r'(\d+)%', line)
        if match:
            return int(match.group(1))
        return None

    def update_telegram_message(self, chat_id):
        while self.is_uploading:
            if self.status_message:
                try:
                    self.bot.edit_message_text(
                        f"Uploading to server... {self.current_percentage}%",
                        chat_id,
                        self.status_message.message_id
                    )
                except:
                    pass
            time.sleep(2)

    def upload(self, input_folder, chat_id=None):
        self.is_uploading = True
        self.current_percentage = 0

        if self.bot and chat_id:
            self.status_message = self.bot.send_message(chat_id, "Starting upload...")
            
            progress_thread = threading.Thread(
                target=self.update_telegram_message,
                args=(chat_id,)
            )
            progress_thread.start()

        try:
            process = subprocess.Popen(
                [
                    'rclone',
                    'copy',
                    input_folder,
                    'od:public/hls-automated',
                    '--verbose',
                    '--progress'
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True
            )

            for line in process.stdout:
                percentage = self.parse_progress(line)
                if percentage is not None:
                    self.current_percentage = percentage

            process.wait()
            self.is_uploading = False

            if self.bot and chat_id and self.status_message:
                self.bot.edit_message_text(
                    "Upload completed successfully!",
                    chat_id,
                    self.status_message.message_id
                )

            return process.returncode == 0

        except Exception as e:
            self.is_uploading = False
            if self.bot and chat_id and self.status_message:
                self.bot.edit_message_text(
                    f"Upload failed: {str(e)}",
                    chat_id,
                    self.status_message.message_id
                )
            return False