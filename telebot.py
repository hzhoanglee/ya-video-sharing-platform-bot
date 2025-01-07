import telebot
import os
from datetime import datetime
from telebot import apihelper
import requests
import json
import time
from encode import VideoProcessor
from rclone import RcloneUploader
from dotenv import load_dotenv

# Initialize bot
bot = telebot.TeleBot(os.getenv('TELEGRAM_TOKEN'))
apihelper.API_URL = "http://127.0.0.1:8999/bot{0}/{1}"

# Create directories for storing files if they don't exist
DOWNLOAD_DIR = 'downloaded_files'
LOGS_DIR = 'message_logs'

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

def log_message(message):
    """Log message details to a file"""
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    log_file = os.path.join(LOGS_DIR, f'message_log_{datetime.now().strftime("%Y-%m-%d")}.txt')
    
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(f"\n{'='*50}\n")
        f.write(f"Timestamp: {timestamp}\n")
        f.write(f"From: {message.from_user.username} (ID: {message.from_user.id})\n")
        f.write(f"Message ID: {message.message_id}\n")
        f.write(f"Content: {message.text or '<no text>'}\n")

def download_file(file_info, file_name, message_id, media_group_id, chat_id):
    """Download file from Telegram with progress updates"""
    try:
        print(file_info.file_path)

        downloaded_file = bot.download_file(file_info.file_path)
        # f_name = file_info.file_path
        # parts = f_name.split(os.path.sep)
        # print(parts)
        # f_get = parts[-2] + "/" + parts[-1]
        base_name = os.path.basename(file_info.file_path)

        if media_group_id:
            use_path = str(media_group_id)
        else:
            use_path = str(message_id)

        save_path = os.path.join(DOWNLOAD_DIR, use_path, file_info.file_unique_id + "___" + base_name)
        if not os.path.exists(os.path.dirname(save_path)):
            os.makedirs(os.path.dirname(save_path))
        

        # link = f"https://rdr.io/{f_get}"
        # auth = ('1', '1')

        # Initialize the download and progress tracking
        # with requests.get(link, auth=auth, stream=True) as r:
        #     if not os.path.exists(os.path.dirname(save_path)):
        #         os.makedirs(os.path.dirname(save_path))
        #     r.raise_for_status()

        #     total_size = int(r.headers.get('content-length', 0))
        #     downloaded_size = 0

        #     progress_message = bot.send_message(chat_id, f"Download started: 0%")
        #     start_time = time.time()

        #     with open(save_path, 'wb') as f:
        #         for chunk in r.iter_content(chunk_size=8192):
        #             if chunk:
        #                 f.write(chunk)
        #                 downloaded_size += len(chunk)

        #                 # Update progress every 2 seconds
        #                 if time.time() - start_time >= 2:
        #                     percentage = (downloaded_size / total_size) * 100
        #                     bot.edit_message_text(
        #                         chat_id=chat_id,
        #                         message_id=progress_message.message_id,
        #                         text=f"Download in progress: {percentage:.2f}%"
        #                     )
        #                     start_time = time.time()

        #     # Final progress update
        #     bot.edit_message_text(
        #         chat_id=chat_id,
        #         message_id=progress_message.message_id,
        #         text=f"Download completed: 100%"
        #     )

        with open(save_path, 'wb') as f:
            f.write(downloaded_file)

        return save_path
    except Exception as e:
        print(f"Error downloading file: {e}")
        bot.send_message(chat_id, f"Error downloading file: {e}")
        return None

def add_caption_to_folder(message_id, caption):
    """Add caption to the folder containing the downloaded file"""
    folder_path = os.path.join(DOWNLOAD_DIR, str(message_id))
    if os.path.exists(folder_path):
        with open(os.path.join(folder_path, 'caption.txt'), 'w', encoding='utf-8') as f:
            f.write(caption)

@bot.message_handler(content_types=['text', 'document', 'audio', 'photo', 'video', 'voice', 'video_note'])
def handle_all_messages(message):
    """Handle all incoming messages"""
    try:
        # Log the message
        log_message(message)
        # write message value to message.txt
        with open('message.txt', 'a', encoding='utf-8') as f:
            f.write(f"{message}\n")

        
        # Handle different types of content
        if message.content_type == 'text':
            bot.reply_to(message, "Text message received and logged!")
            
        elif message.content_type == 'document':
            file_info = bot.get_file(message.document.file_id)
            file_name = message.document.file_name
            save_path = download_file(file_info, file_name, message.message_id, message.media_group_id, message.chat.id)
            bot.reply_to(message, f"Document saved to: {save_path}")
            
        elif message.content_type == 'audio':
            file_info = bot.get_file(message.audio.file_id)
            file_name = message.audio.file_name or f"audio.{message.audio.mime_type.split('/')[-1]}"
            save_path = download_file(file_info, file_name, message.message_id, message.media_group_id, message.chat.id)
            bot.reply_to(message, f"Audio saved to: {save_path}")
            
        elif message.content_type == 'photo':
            # Get the largest photo (last element in photos array)
            file_info = bot.get_file(message.photo[-1].file_id)
            save_path = download_file(file_info, 'photo.jpg', message.message_id, message.media_group_id, message.chat.id)
            bot.reply_to(message, f"Photo saved to: {save_path}")
            
        elif message.content_type == 'video':
            for attempt in range(5):
                try:
                    file_info = bot.get_file(message.video.file_id)
                    save_path = download_file(file_info, 'video.mp4', message.message_id, message.media_group_id, message.chat.id)
                    break
                except Exception as e:
                    print(f"Attempt {attempt + 1} failed: {e}")
                    time.sleep(2)
            else:
                bot.reply_to(message, "Failed to download video after 5 attempts.")
                return

            bot.reply_to(message, f"Video saved to: {save_path}")
            
            # Process video
            processor = VideoProcessor(bot)
            processor.process_video(save_path, message.chat.id, message.caption)
            
            # Upload processed files
            uploader = RcloneUploader(bot)
            hls_folder = os.path.join(os.path.abspath(os.path.join(os.getcwd(), os.pardir)), "hls-automated")
            uploader.upload(hls_folder, message.chat.id)

            bot.send_message(message.chat.id, "Video processing and upload completed!")
            
        elif message.content_type == 'voice':
            file_info = bot.get_file(message.voice.file_id)
            save_path = download_file(file_info, 'voice.ogg', message.message_id)
            bot.reply_to(message, f"Voice message saved to: {save_path}")
            
        elif message.content_type == 'video_note':
            file_info = bot.get_file(message.video_note.file_id)
            save_path = download_file(file_info, 'video_note.mp4', message.message_id)
            bot.reply_to(message, f"Video note saved to: {save_path}")

    except Exception as e:
        print(f"Error processing message: {e}")
        bot.reply_to(message, "Sorry, there was an error processing your message.")

if __name__ == "__main__":
    print("Bot started...")
    bot.polling(none_stop=True)
