import os
import subprocess
import random
import requests
from googletrans import Translator
from slugify import slugify
from moviepy import VideoFileClip
import json
import re
import unicodedata
import time
import datetime
from dotenv import load_dotenv

class VideoProcessor:
    def __init__(self, bot=None):
        load_dotenv()
        self.translator = Translator()
        self.hls_target = os.getenv('HLS_TARGET')
        self.bot = bot


    def get_video_length(self, filename):
        clip = VideoFileClip(filename)
        seconds = int(clip.duration)
        minutes = seconds // 60
        remaining_seconds = seconds % 60
        clip.close()
        return f"{minutes:02d}:{remaining_seconds:02d}"

    def upload_random_frame(self, video_path):
        clip = VideoFileClip(video_path)
        random_time = random.uniform(0, clip.duration)
        frame = clip.get_frame(random_time)
        
        temp_image = "temp_frame.png"
        clip.save_frame(temp_image, t=random_time)
        clip.close()
        
        with open(temp_image, 'rb') as img_file:
            files = {'image': img_file}
            response = requests.post(os.getenv('IMG_ENDPOINT'), files=files)
            print(response.json())
        
        try:
            os.remove(temp_image)
        except PermissionError:
            time.sleep(1)
            try:
                os.remove(temp_image)
            except:
                print(f"Could not remove temporary file: {temp_image}")
        
        return response.json()['url']

    def process_video(self, video_path, chat_id, message_caption = None):
        # Handle filename if it starts with '-'
        video_file = os.path.basename(video_path)
        if video_file[0] == '-':
            new_path = os.path.join(os.path.dirname(video_path), video_file[1:])
            os.rename(video_path, new_path)
            video_path = new_path
            video_file = video_file[1:]
        
        # Translate filename to English
        original_name = os.path.splitext(video_file)[0]
        translated_title = self.translator.translate(original_name, dest='en').text
        if message_caption is None:
            message_caption = translated_title
            translated_caption = translated_title
        else:
            translated_caption = self.translator.translate(message_caption, dest='en').text
        
        # Create slug
        slug = slugify(translated_title)
        if len(slug) > 50:
            random_string = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz', k=5))
            slug = slug[:30] + slug[-10:] + random_string
        
        # Create HLS versions
        ab_dir = os.path.abspath(os.path.join(os.getcwd(), os.pardir))
        hls_dir = os.path.join(ab_dir, "hls-automated", slug)
        os.makedirs(hls_dir, exist_ok=True)
        
        # Get video dimensions
        probe = subprocess.check_output([
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height', '-of', 'json', video_path
        ])
        dimensions = json.loads(probe)['streams'][0]
        threads_count = os.getenv('THREADS_COUNT')
        
        original_command = [
            'ffmpeg', '-i', video_path,
            '-c:v', 'h264', '-c:a', 'aac',
            '-hls_time', '10',
            '-hls_list_size', '0',
            '-threads', threads_count,
            f'{hls_dir}/original.m3u8'
        ]
        self.bot.send_message(chat_id, "Starting original resolution conversion...")
        self.run_ffmpeg_with_progress(original_command, None, chat_id)

        # Convert to 720p
        p720_command = [
            'ffmpeg', '-i', video_path,
            '-c:v', 'h264', '-c:a', 'aac',
            '-vf', 'scale=-2:720',
            '-hls_time', '10',
            '-hls_list_size', '0',
            '-threads', threads_count,
            f'{hls_dir}/720p.m3u8'
        ]
        self.bot.send_message(chat_id, "Starting 720p conversion...")
        self.run_ffmpeg_with_progress(p720_command, None, chat_id)
        
        preview_url = self.upload_random_frame(video_path)
        
        video_length = self.get_video_length(video_path)
        
        # Prepare and send POST request
        video_data = {
            "title": translated_caption,
            "description": self.sanitize_text(message_caption),
            "slug": slug,
            "preview_image_url": preview_url,
            "video_url_720p": f"{self.hls_target}/{slug}/720p.m3u8",
            "video_url_1080p": f"{self.hls_target}/{slug}/original.m3u8",
            "length": video_length
        }

        print(video_data)
        
        response = requests.post(os.getenv('YAVSP_ENDPOINT'), json=video_data)
        if response.status_code == 200:
            re = (f"Processed {video_file}: {response.status_code}")
        else:
            re = (f"Error processing {video_file}: {response.status_code}. {response.text}")

        self.bot.send_message(chat_id, re)

        self.scan_directory(hls_dir)

        return re
    
    def modify_m3u8(self, file_path, base_url=None):
        if base_url is None:
            base_url = self.hls_target

        with open(file_path, 'r') as file:
            content = file.read()
        
        dir_name = os.path.basename(os.path.dirname(file_path))
        
        def replace_ts(match):
            ts_file = match.group(1)
            return f"{base_url}/{dir_name}/{ts_file}"
        
        modified_content = re.sub(r'^(.*?\.ts)$', replace_ts, content, flags=re.MULTILINE)
        
        with open(file_path, 'w') as file:
            file.write(modified_content)

    def scan_directory(self, directory):
        # Walk through all directories and files
        for root, dirs, files in os.walk(directory):
            for file in files:
                if file.endswith('.m3u8'):
                    file_path = os.path.join(root, file)
                    print(f"Processing: {file_path}")
                    self.modify_m3u8(file_path)


    def run_ffmpeg_with_progress(self, command, message_id, chat_id):
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )

        duration = None
        previous_progress = -1
        status_message = self.bot.send_message(chat_id, "Starting encoding: 0%")

        for line in process.stderr:
            # Get duration if not already found
            if duration is None:
                duration_match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2})", line)
                if duration_match:
                    hours, minutes, seconds = map(int, duration_match.groups())
                    duration = hours * 3600 + minutes * 60 + seconds

            time_match = re.search(r"time=(\d{2}):(\d{2}):(\d{2})", line)
            if time_match and duration:
                hours, minutes, seconds = map(int, time_match.groups())
                current_time = hours * 3600 + minutes * 60 + seconds
                progress = int((current_time / duration) * 100)
                print(progress)

                if progress != previous_progress:
                    try:
                        now = datetime.datetime.now()
                        n = now.strftime("%Y-%m-%d %H:%M:%S")
                        self.bot.edit_message_text(
                            f"[{str(n)}]Encoding progress: {progress}%",
                            chat_id,
                            status_message.message_id
                        )
                        previous_progress = progress
                    except Exception as e:
                        pass

        process.wait()
        now = datetime.datetime.now()
        n = now.strftime("%Y-%m-%d %H:%M:%S")
        self.bot.edit_message_text(
            str(n)+"Encoding completed!",
            chat_id,
            status_message.message_id
        )
        return process.returncode == 0

    
    def sanitize_text(self, text):
        if text is None:
            return ""
        
        try:
            normalized = unicodedata.normalize('NFKD', text)
            
            cleaned_text = ''
            for char in normalized:
                if ord(char) < 256 or char.isalnum() or char in [' ', '-', '_', '.', ',']:
                    cleaned_text += char
            
            cleaned_text = ' '.join(cleaned_text.split())
            
            if not cleaned_text.strip():
                return "No description"
            
            return cleaned_text[:500]  # Limit length to 500 characters
        except Exception as e:
            print(f"Error sanitizing text: {e}")
            return "No description"
