import asyncio
import logging
import sqlite3
import requests
import os
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ChatMemberHandler
)
from telegram.constants import ChatMemberStatus
from telegram.ext import Application

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8428357636:AAFmd0_OnbvQpA0w2UcgTCekf5ends2DkBI"
QURAN_PAGES = 604

IMAGES_PATH = Path("images")
QURAN_PAGES_PATH = IMAGES_PATH / "quran_pages"
AZKAR_PATH = IMAGES_PATH / "azkar"
BAKARAH_QIYAM_PATH = IMAGES_PATH / "bakarah_qiyam"
PDF_PATH = Path("pdfs")

IMAGES_PATH.mkdir(exist_ok=True)
QURAN_PAGES_PATH.mkdir(exist_ok=True)
AZKAR_PATH.mkdir(exist_ok=True)
BAKARAH_QIYAM_PATH.mkdir(exist_ok=True)
PDF_PATH.mkdir(exist_ok=True)

# ======================== قاعدة البيانات ========================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('wird_bot.db', check_same_thread=False)
        self.create_tables()
        self.upgrade_database()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                chat_id INTEGER,
                daily_pages INTEGER DEFAULT 2,
                bakarah_enabled BOOLEAN DEFAULT 0,
                morning_azkar_enabled BOOLEAN DEFAULT 1,
                evening_azkar_enabled BOOLEAN DEFAULT 1,
                morning_azkar_time TEXT DEFAULT '06:00',
                evening_azkar_time TEXT DEFAULT '17:00',
                kahf_enabled BOOLEAN DEFAULT 1,
                mulk_enabled BOOLEAN DEFAULT 1,
                quran_time TEXT DEFAULT '09:00',
                current_page INTEGER DEFAULT 1,
                white_days_reminder BOOLEAN DEFAULT 1,
                timezone_offset INTEGER DEFAULT 3,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.conn.commit()
    
    def upgrade_database(self):
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in cursor.fetchall()]
        
        columns_to_add = {
            'morning_azkar_enabled': 'BOOLEAN DEFAULT 1',
            'evening_azkar_enabled': 'BOOLEAN DEFAULT 1',
            'white_days_reminder': 'BOOLEAN DEFAULT 1',
            'timezone_offset': 'INTEGER DEFAULT 3'
        }
        
        for column_name, column_def in columns_to_add.items():
            if column_name not in columns:
                try:
                    cursor.execute(f'ALTER TABLE users ADD COLUMN {column_name} {column_def}')
                    self.conn.commit()
                except:
                    pass
    
    def add_user(self, user_id: int, chat_id: int):
        cursor = self.conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO users (user_id, chat_id) VALUES (?, ?)', (user_id, chat_id))
        self.conn.commit()
    
    def get_user(self, user_id: int):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        return cursor.fetchone()
    
    def update_user_setting(self, user_id: int, setting: str, value):
        cursor = self.conn.cursor()
        cursor.execute(f'UPDATE users SET {setting} = ? WHERE user_id = ?', (value, user_id))
        self.conn.commit()
    
    def get_all_users(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users')
        return cursor.fetchall()
    
    def update_current_page(self, user_id: int, page: int):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE users SET current_page = ? WHERE user_id = ?', (page, user_id))
        self.conn.commit()

db = Database()



# ===================================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
APP_URL = "https://wardmuslimbot.onrender.com"  # انسخه لاحقاً من Render

app = Application.builder().token(BOT_TOKEN).build()
app.run_webhook(
    listen="0.0.0.0",
    port=10000,
    url_path=BOT_TOKEN,
    webhook_url=f"{APP_URL}/{BOT_TOKEN}"
)

# ======================== API التقويم الهجري ========================
class IslamicCalendar:
    @staticmethod
    def get_hijri_date():
        try:
            response = requests.get('http://api.aladhan.com/v1/gToH', timeout=10)
            if response.status_code == 200:
                data = response.json()
                hijri = data['data']['hijri']
                return {
                    'day': int(hijri['day']),
                    'month': int(hijri['month']['number']),
                    'month_name': hijri['month']['ar'],
                    'year': hijri['year']
                }
        except:
            pass
        return None
    
    @staticmethod
    def get_prayer_times(city="Makkah", country="Saudi Arabia"):
        try:
            response = requests.get(
                f'http://api.aladhan.com/v1/timingsByCity',
                params={'city': city, 'country': country},
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                timings = data['data']['timings']
                return {
                    'Fajr': timings['Fajr'],
                    'Dhuhr': timings['Dhuhr'],
                    'Asr': timings['Asr'],
                    'Maghrib': timings['Maghrib'],
                    'Isha': timings['Isha']
                }
        except:
            pass
        return None
    
    @staticmethod
    def check_islamic_occasions():
        hijri = IslamicCalendar.get_hijri_date()
        if not hijri:
            return None
        
        day = hijri['day']
        month = hijri['month']
        
        occasions = {
            (1, 1): "🌙 رأس السنة الهجرية",
            (1, 10): "🕌 صيام يوم عاشوراء",
            (9, 1): "🌙 رمضان كريم",
            (9, 27): "⭐ ليلة القدر",
            (10, 1): "🎉 عيد الفطر المبارك",
            (10, 9): "🕋 يوم عرفة",
            (10, 10): "🎊 عيد الأضحى المبارك"
        }
        
        if day in [13, 14, 15]:
            return f"⚪ صيام الأيام البيض ({day} {hijri['month_name']})"
        
        return occasions.get((month, day))
    
    @staticmethod
    def is_day_before_white_days():
        hijri = IslamicCalendar.get_hijri_date()
        return hijri and hijri['day'] == 12

# ======================== محتوى الأذكار ========================
class IslamicContent:
    TASBIH_TYPES = [
        "📿 *تسبيح*\n\n🔹 سبحان الله (33)\n🔹 الحمد لله (33)\n🔹 الله أكبر (34)",
        "📿 *تسبيح*\n\n🔹 سبحان الله وبحمده (100 مرة)",
        "📿 *تسبيح*\n\n🔹 سبحان الله العظيم وبحمده",
        "📿 *تسبيح*\n\n🔹 سبحان الله والحمد لله ولا إله إلا الله والله أكبر",
        "📿 *تسبيح*\n\n🔹 لا إله إلا الله وحده لا شريك له (10 مرات)"
    ]
    
    ISTIGHFAR_TYPES = [
        "🤲 *استغفار*\n\n🔹 أستغفر الله العظيم وأتوب إليه (3 مرات)",
        "🤲 *سيد الاستغفار*\n\n🔹 اللهم أنت ربي لا إله إلا أنت، خلقتني وأنا عبدك، وأنا على عهدك ووعدك ما استطعت، أعوذ بك من شر ما صنعت، أبوء لك بنعمتك عليّ، وأبوء بذنبي فاغفر لي، فإنه لا يغفر الذنوب إلا أنت.",
        "🤲 *استغفار*\n\n🔹 أستغفر الله وأتوب إليه (100 مرة)",
        "🤲 *استغفار*\n\n🔹 رب اغفر لي وتب علي (100 مرة)",
        "🤲 *استغفار*\n\n🔹 اللهم اغفر لي ذنبي كلّه، دقّه وجلّه، وأوله وآخره، وعلانيته وسرّه"
    ]
    
    GENERAL_AZKAR = [
        "💎 *ذكر*\n\n🔹 لا حول ولا قوة إلا بالله",
        "💎 *الباقيات الصالحات*\n\n🔹 سبحان الله والحمد لله ولا إله إلا الله والله أكبر",
        "💎 *الصلاة على النبي ﷺ*\n\n🔹 اللهم صل وسلم وبارك على سيدنا محمد",
        "💎 *كلمتان خفيفتان*\n\n🔹 سبحان الله وبحمده، سبحان الله العظيم",
        "💎 *أفضل الذكر*\n\n🔹 لا إله إلا الله"
    ]
    
    @staticmethod
    def get_random_dhikr():
        dhikr_type = random.choice(['tasbih', 'istighfar', 'general'])
        if dhikr_type == 'tasbih':
            return random.choice(IslamicContent.TASBIH_TYPES)
        elif dhikr_type == 'istighfar':
            return random.choice(IslamicContent.ISTIGHFAR_TYPES)
        else:
            return random.choice(IslamicContent.GENERAL_AZKAR)

# ======================== إدارة الصور ========================
class MediaManager:
    @staticmethod
    def get_quran_page_image(page_number: int) -> Optional[Path]:
        for ext in ['jpg', 'png', 'jpeg']:
            page_file = QURAN_PAGES_PATH / f"{page_number:04d}.{ext}"
            if page_file.exists():
                return page_file
        return None
    
    @staticmethod
    def get_morning_azkar_image() -> Optional[Path]:
        for ext in ['jpg', 'png', 'jpeg']:
            image_file = AZKAR_PATH / f"morning_azkar.{ext}"
            if image_file.exists():
                return image_file
        return None
    
    @staticmethod
    def get_evening_azkar_image() -> Optional[Path]:
        for ext in ['jpg', 'png', 'jpeg']:
            image_file = AZKAR_PATH / f"evening_azkar.{ext}"
            if image_file.exists():
                return image_file
        return None
    
    @staticmethod
    def get_mulk_image() -> Optional[Path]:
        for ext in ['jpg', 'png', 'jpeg']:
            image_file = AZKAR_PATH / f"surah_mulk.{ext}"
            if image_file.exists():
                return image_file
        return None
    
    @staticmethod
    def get_bakarah_qiyam_images(start_page: int, end_page: int) -> list:
        images = []
        for page in range(start_page, end_page + 1):
            for ext in ['jpg', 'png', 'jpeg']:
                page_file = BAKARAH_QIYAM_PATH / f"{page:03d}.{ext}"
                if page_file.exists():
                    images.append(page_file)
                    break
        return images
    
    @staticmethod
    def get_kahf_pdf() -> Optional[Path]:
        pdf_file = PDF_PATH / "surah_kahf.pdf"
        return pdf_file if pdf_file.exists() else None

# ======================== معالج إضافة البوت للمجموعات ========================
async def track_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تشغيل تلقائي عند إضافة البوت لمجموعة أو قناة"""
    result = update.my_chat_member
    if result is None:
        return
    
    new_status = result.new_chat_member.status
    chat = result.chat
    
    if new_status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR]:
        # تم إضافة البوت للمجموعة/القناة
        db.add_user(chat.id, chat.id)
        
        welcome_message = f"""
السلام عليكم ورحمة الله وبركاته 🌙

تم تفعيل *وِرْدُ المُسْلِم*   {'للمجموعة' if chat.type in ['group', 'supergroup'] else 'للقناة'} 

📚 سيتم إرسال التذكيرات:
• الورد اليومي من القرآن
• أذكار الصباح والمساء
• سورة الكهف (الجمعة)
• سورة البقرة (اختياري)
• المناسبات الإسلامية
• أذكار متنوعة

🕌 بارك الله فيكم
        """
        
        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text=welcome_message,
                parse_mode='Markdown'
            )
        except:
            pass

# ======================== وظائف البوت ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    
    db.add_user(user.id, chat_id)
    
    keyboard = [
        [InlineKeyboardButton("⚙️ إعداداتي", callback_data='settings')],
        [InlineKeyboardButton("📖 الورد اليومي", callback_data='daily_wird')],
        [InlineKeyboardButton("📿 أذكار سريعة", callback_data='quick_azkar')],
        [InlineKeyboardButton("ℹ️ المساعدة", callback_data='help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if chat_type in ['group', 'supergroup', 'channel']:
        welcome_message = """
السلام عليكم ورحمة الله وبركاته 🌙

*وِرْدُ المُسْلِم*

📚 التذكيرات:
• الورد اليومي (صور)
• أذكار الصباح والمساء
• سورة الكهف (الجمعة)
• سورة البقرة (اختياري)
• المناسبات الإسلامية

🕌 بارك الله فيكم
        """
    else:
        welcome_message = f"""
السلام عليكم {user.first_name} 🌙

*وِرْدُ المُسْلِم*

📚 سأساعدك في:
• قراءة الورد اليومي
• التذكير بالأذكار
• المناسبات الإسلامية

اضغط الأزرار أدناه 👇
        """
    
    await update.message.reply_text(
        welcome_message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📖 عدد الصفحات", callback_data='set_pages')],
        [InlineKeyboardButton("⏰ وقت الورد", callback_data='set_quran_time')],
        [InlineKeyboardButton("🌍 التوقيت", callback_data='set_timezone')],
        [InlineKeyboardButton("📗 سورة البقرة", callback_data='set_bakarah')],
        [InlineKeyboardButton("🔔 التنبيهات", callback_data='set_notifications')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='back_main')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "⚙️ *الإعدادات*",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def set_daily_pages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("1", callback_data='pages_1'),
         InlineKeyboardButton("2", callback_data='pages_2'),
         InlineKeyboardButton("3", callback_data='pages_3')],
        [InlineKeyboardButton("5", callback_data='pages_5'),
         InlineKeyboardButton("10", callback_data='pages_10'),
         InlineKeyboardButton("20", callback_data='pages_20')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "📖 *عدد الصفحات*",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def set_quran_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("05:00 صباح", callback_data='qtime_05:00'),
         InlineKeyboardButton("06:00 صباح", callback_data='qtime_06:00'),
         InlineKeyboardButton("07:00 صباح", callback_data='qtime_07:00')],
        [InlineKeyboardButton("08:00 صباح", callback_data='qtime_08:00'),
         InlineKeyboardButton("09:00 صباح", callback_data='qtime_09:00'),
         InlineKeyboardButton("10:00 صباح", callback_data='qtime_10:00')],
        [InlineKeyboardButton("08:00 مساء", callback_data='qtime_20:00'),
         InlineKeyboardButton("09:00 مساء", callback_data='qtime_21:00'),
         InlineKeyboardButton("10:00 مساء", callback_data='qtime_22:00')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    user = db.get_user(query.from_user.id)
    current_time = user[10] if user and len(user) > 10 else '09:00'
    
    await query.edit_message_text(
        f"⏰ *وقت الورد*\n\nالحالي: {current_time}",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def set_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🇸🇦 السعودية (UTC+3)", callback_data='tz_3')],
        [InlineKeyboardButton("🇦🇪 الإمارات (UTC+4)", callback_data='tz_4')],
        [InlineKeyboardButton("🇪🇬 مصر (UTC+2)", callback_data='tz_2')],
        [InlineKeyboardButton("🇯🇴 الأردن (UTC+3)", callback_data='tz_3')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    user = db.get_user(query.from_user.id)
    current_tz = user[13] if user and len(user) > 13 else 3
    
    await query.edit_message_text(
        f"🌍 *التوقيت*\n\nالحالي: UTC+{current_tz}",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def set_bakarah_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = db.get_user(query.from_user.id)
    bakarah_status = "مفعّلة ✅" if user and len(user) > 3 and user[3] else "معطّلة ❌"
    
    keyboard = [
        [InlineKeyboardButton("تفعيل ✅" if not (user and len(user) > 3 and user[3]) else "تعطيل ❌", 
                            callback_data='toggle_bakarah')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"📗 *سورة البقرة*\n\nالحالة: {bakarah_status}\n\n12 صفحة على 5 صلوات",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def set_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = db.get_user(query.from_user.id)
    
    kahf_enabled = user[8] if user and len(user) > 8 else 1
    mulk_enabled = user[9] if user and len(user) > 9 else 1
    white_days_enabled = user[12] if user and len(user) > 12 else 1
    
    keyboard = [
        [InlineKeyboardButton(f"{'✅' if kahf_enabled else '❌'} سورة الكهف", callback_data='toggle_kahf')],
        [InlineKeyboardButton(f"{'✅' if mulk_enabled else '❌'} سورة الملك", callback_data='toggle_mulk')],
        [InlineKeyboardButton(f"{'✅' if white_days_enabled else '❌'} الأيام البيض", callback_data='toggle_white_days')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🔔 *التنبيهات*",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    if data == 'back_main':
        keyboard = [
            [InlineKeyboardButton("⚙️ إعداداتي", callback_data='settings')],
            [InlineKeyboardButton("📖 الورد اليومي", callback_data='daily_wird')],
            [InlineKeyboardButton("📿 أذكار سريعة", callback_data='quick_azkar')],
            [InlineKeyboardButton("ℹ️ المساعدة", callback_data='help')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("🏠 *القائمة*", reply_markup=reply_markup, parse_mode='Markdown')
    
    elif data == 'settings':
        await settings_menu(update, context)
    elif data == 'set_pages':
        await set_daily_pages(update, context)
    elif data == 'set_quran_time':
        await set_quran_time(update, context)
    elif data == 'set_timezone':
        await set_timezone(update, context)
    elif data == 'set_bakarah':
        await set_bakarah_setting(update, context)
    elif data == 'set_notifications':
        await set_notifications(update, context)
    
    elif data.startswith('pages_'):
        pages = int(data.split('_')[1])
        db.update_user_setting(user_id, 'daily_pages', pages)
        await query.edit_message_text(f"✅ {pages} صفحة", parse_mode='Markdown')
        await asyncio.sleep(1)
        await settings_menu(update, context)
    
    elif data.startswith('qtime_'):
        time_str = data.split('_')[1]
        db.update_user_setting(user_id, 'quran_time', time_str)
        
        job_name = f'daily_wird_{user_id}'
        current_jobs = context.application.job_queue.get_jobs_by_name(job_name)
        for job in current_jobs:
            job.schedule_removal()
        
        user = db.get_user(user_id)
        tz_offset = user[13] if user and len(user) > 13 else 3
        
        context.application.job_queue.run_daily(
            lambda c: send_daily_wird_single(c, user_id),
            time=datetime.strptime(time_str, '%H:%M').time(),
            name=job_name
        )
        
        await query.edit_message_text(f"✅ الوقت: {time_str}", parse_mode='Markdown')
        await asyncio.sleep(1)
        await settings_menu(update, context)
    
    elif data.startswith('tz_'):
        tz = int(data.split('_')[1])
        db.update_user_setting(user_id, 'timezone_offset', tz)
        await query.edit_message_text(f"✅ التوقيت: UTC+{tz}", parse_mode='Markdown')
        await asyncio.sleep(1)
        await settings_menu(update, context)
    
    elif data == 'toggle_bakarah':
        user = db.get_user(user_id)
        current_value = user[3] if user and len(user) > 3 else 0
        new_value = 0 if current_value else 1
        db.update_user_setting(user_id, 'bakarah_enabled', new_value)
        await set_bakarah_setting(update, context)
    
    elif data == 'toggle_kahf':
        user = db.get_user(user_id)
        current_value = user[8] if user and len(user) > 8 else 1
        new_value = 0 if current_value else 1
        db.update_user_setting(user_id, 'kahf_enabled', new_value)
        await set_notifications(update, context)
    
    elif data == 'toggle_mulk':
        user = db.get_user(user_id)
        current_value = user[9] if user and len(user) > 9 else 1
        new_value = 0 if current_value else 1
        db.update_user_setting(user_id, 'mulk_enabled', new_value)
        await set_notifications(update, context)
    
    elif data == 'toggle_white_days':
        user = db.get_user(user_id)
        current_value = user[12] if user and len(user) > 12 else 1
        new_value = 0 if current_value else 1
        db.update_user_setting(user_id, 'white_days_reminder', new_value)
        await set_notifications(update, context)
    
    elif data == 'daily_wird':
        user = db.get_user(user_id)
        if user:
            pages = user[2] if len(user) > 2 else 2
            current_page = user[11] if len(user) > 11 else 1
            quran_time = user[10] if len(user) > 10 else '09:00'
            await query.edit_message_text(
                f"📖 *وردك*\n\nصفحات: {pages}\nالحالية: {current_page}\nالوقت: {quran_time}",
                parse_mode='Markdown'
            )
    
    elif data == 'quick_azkar':
        keyboard = [
            [InlineKeyboardButton("📿 تسبيح", callback_data='random_tasbih')],
            [InlineKeyboardButton("🤲 استغفار", callback_data='random_istighfar')],
            [InlineKeyboardButton("💎 ذكر", callback_data='random_dhikr')],
            [InlineKeyboardButton("🔙 رجوع", callback_data='back_main')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("📿 *أذكار*", reply_markup=reply_markup, parse_mode='Markdown')
    
    elif data in ['random_tasbih', 'random_istighfar', 'random_dhikr']:
        await query.edit_message_text(IslamicContent.get_random_dhikr(), parse_mode='Markdown')
    
    elif data == 'help':
        help_text = """
ℹ️ *وِرْدُ المُسْلِم*

/start - البدء

*المميزات:*
📖 الورد اليومي (صور)
📗 سورة البقرة (12 صفحة)
☀️ أذكار الصباح والمساء
🌙 سورة الملك
🕋 سورة الكهف (الجمعة)
⚪ الأيام البيض
📅 المناسبات

*للمجموعات:*
أضف البوت وسيعمل تلقائياً

🤲 بارك الله فيك
        """
        await query.edit_message_text(help_text, parse_mode='Markdown')

# ======================== المهام المجدولة ========================
async def send_morning_azkar(context: ContextTypes.DEFAULT_TYPE):
    users = db.get_all_users()
    image_path = MediaManager.get_morning_azkar_image()
    caption = "☀️ *أذكار الصباح*\n\n﴿فَاذْكُرُونِي أَذْكُرْكُمْ﴾"
    
    for user in users:
        morning_enabled = user[4] if len(user) > 4 else 1
        if morning_enabled:
            try:
                if image_path:
                    with open(image_path, 'rb') as photo:
                        await context.bot.send_photo(chat_id=user[1], photo=photo, caption=caption, parse_mode='Markdown')
                else:
                    await context.bot.send_message(chat_id=user[1], text=caption, parse_mode='Markdown')
            except:
                pass

async def send_evening_azkar(context: ContextTypes.DEFAULT_TYPE):
    users = db.get_all_users()
    image_path = MediaManager.get_evening_azkar_image()
    caption = "🌙 *أذكار المساء*\n\n﴿وَاذْكُر رَّبَّكَ﴾"
    
    for user in users:
        evening_enabled = user[5] if len(user) > 5 else 1
        if evening_enabled:
            try:
                if image_path:
                    with open(image_path, 'rb') as photo:
                        await context.bot.send_photo(chat_id=user[1], photo=photo, caption=caption, parse_mode='Markdown')
                else:
                    await context.bot.send_message(chat_id=user[1], text=caption, parse_mode='Markdown')
            except:
                pass

async def send_daily_wird_single(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    user = db.get_user(user_id)
    if not user:
        return
    
    try:
        pages = user[2] if len(user) > 2 else 2
        current_page = user[11] if len(user) > 11 else 1
        
        end_page = current_page + pages - 1
        if end_page > QURAN_PAGES:
            end_page = QURAN_PAGES
            current_page = 1
        
        caption = f"📖 *الورد اليومي*\n\n إِنَّ هَذَا الْقُرْآنَ يَهْدِي لِلَّتِي هِيَ أَقْوَمُ [الإسراء:9]\n\nالصفحات: {current_page} - {end_page}"
        
        # جمع الصور
        media_group = []
        for page_num in range(current_page, min(current_page + 10, end_page + 1)):
            image_path = MediaManager.get_quran_page_image(page_num)
            if image_path:
                with open(image_path, 'rb') as photo:
                    if page_num == current_page:
                        media_group.append(InputMediaPhoto(media=photo.read(), caption=caption, parse_mode='Markdown'))
                    else:
                        media_group.append(InputMediaPhoto(media=photo.read()))
        
        if media_group:
            await context.bot.send_media_group(chat_id=user[1], media=media_group)
        
        # إذا كان هناك صفحات إضافية
        if end_page - current_page >= 10:
            for page_num in range(current_page + 10, end_page + 1):
                image_path = MediaManager.get_quran_page_image(page_num)
                if image_path:
                    with open(image_path, 'rb') as photo:
                        await context.bot.send_photo(chat_id=user[1], photo=photo)
                    await asyncio.sleep(0.3)
        
        next_page = end_page + 1
        if next_page > QURAN_PAGES:
            next_page = 1
        db.update_current_page(user[0], next_page)
    except:
        pass

async def send_mulk(context: ContextTypes.DEFAULT_TYPE):
    users = db.get_all_users()
    image_path = MediaManager.get_mulk_image()
    caption = "🌙 *سورة الملك*\n\n أن النبيَّ صلَّى اللهُ عليهِ وسلَّمَ كان لا ينامُ حتى يقرأَ الم تنزيلُ و تباركَ الذي بيدِه الملكُ "
    
    for user in users:
        mulk_enabled = user[9] if len(user) > 9 else 1
        if mulk_enabled:
            try:
                if image_path:
                    with open(image_path, 'rb') as photo:
                        await context.bot.send_photo(chat_id=user[1], photo=photo, caption=caption, parse_mode='Markdown')
                else:
                    await context.bot.send_message(chat_id=user[1], text=caption, parse_mode='Markdown')
            except:
                pass

async def send_friday_kahf(context: ContextTypes.DEFAULT_TYPE):
    if datetime.now().weekday() == 4:
        users = db.get_all_users()
        pdf_path = MediaManager.get_kahf_pdf()
        caption = "🕌 *جمعة مباركة*\n\n📖 سورة الكهف\n\n💚 الصلاة على النبي ﷺ"
        
        for user in users:
            kahf_enabled = user[8] if len(user) > 8 else 1
            if kahf_enabled:
                try:
                    if pdf_path:
                        with open(pdf_path, 'rb') as document:
                            await context.bot.send_document(chat_id=user[1], document=document, caption=caption, parse_mode='Markdown', filename="سورة_الكهف.pdf")
                    else:
                        await context.bot.send_message(chat_id=user[1], text=caption, parse_mode='Markdown')
                except:
                    pass

async def send_bakarah_part(context: ContextTypes.DEFAULT_TYPE, prayer_name: str):
    users = db.get_all_users()
    
    parts = {
        'Fajr': (1, 3),
        'Dhuhr': (4, 6),
        'Asr': (7, 9),
        'Maghrib': (10, 10),
        'Isha': (11, 12)
    }
    
    if prayer_name not in parts:
        return
    
    start_page, end_page = parts[prayer_name]
    images = MediaManager.get_bakarah_qiyam_images(start_page, end_page)
    
    prayers_ar = {'Fajr': 'الفجر', 'Dhuhr': 'الظهر', 'Asr': 'العصر', 'Maghrib': 'المغرب', 'Isha': 'العشاء'}
    caption = f"📗 *سورة البقرة*\n\nبعد {prayers_ar[prayer_name]}\nصفحات {start_page}-{end_page}"
    
    for user in users:
        bakarah_enabled = user[3] if len(user) > 3 else 0
        if bakarah_enabled:
            try:
                media_group = []
                for idx, image_path in enumerate(images):
                    with open(image_path, 'rb') as photo:
                        if idx == 0:
                            media_group.append(InputMediaPhoto(media=photo.read(), caption=caption, parse_mode='Markdown'))
                        else:
                            media_group.append(InputMediaPhoto(media=photo.read()))
                
                if media_group:
                    await context.bot.send_media_group(chat_id=user[1], media=media_group)
            except:
                pass

async def check_islamic_occasions_daily(context: ContextTypes.DEFAULT_TYPE):
    occasion = IslamicCalendar.check_islamic_occasions()
    
    if occasion:
        users = db.get_all_users()
        hijri = IslamicCalendar.get_hijri_date()
        
        if hijri:
            message = f"🌙 *مناسبة*\n\n📅 {hijri['day']} {hijri['month_name']}\n\n{occasion}"
            for user in users:
                try:
                    await context.bot.send_message(chat_id=user[1], text=message, parse_mode='Markdown')
                except:
                    pass

async def send_white_days_reminder(context: ContextTypes.DEFAULT_TYPE):
    if IslamicCalendar.is_day_before_white_days():
        users = db.get_all_users()
        hijri = IslamicCalendar.get_hijri_date()
        
        if hijri:
            message = f"⚪ *الأيام البيض*\n\nغدًا صيام الأيام البيض\n يوم 13 و14 و15 "
            for user in users:
                white_days_enabled = user[12] if len(user) > 12 else 1
                if white_days_enabled:
                    try:
                        await context.bot.send_message(chat_id=user[1], text=message, parse_mode='Markdown')
                    except:
                        pass

async def send_random_dhikr(context: ContextTypes.DEFAULT_TYPE):
    users = db.get_all_users()
    message = IslamicContent.get_random_dhikr()
    
    for user in users:
        try:
            await context.bot.send_message(chat_id=user[1], text=message, parse_mode='Markdown')
        except:
            pass

async def send_qiyam_reminder(context: ContextTypes.DEFAULT_TYPE):
    users = db.get_all_users()
    message = "🌙 *قيام الليل*\n\nالثلث الأخير من الليل \n\n قيام الليل له فضل عظيم، فهو وسيلة للقرب من الله، ومكفر للذنوب، ومنهاة عن الإثم، كما أنه يقرب العبد من ربه ويجعله من القانتين، بالإضافة إلى أنه وقت لإجابة الدعاء وتفريج الهموم، ويفتح أبواب الخير والبركة 🍃"
    
    for user in users:
        try:
            await context.bot.send_message(chat_id=user[1], text=message, parse_mode='Markdown')
        except:
            pass

# ======================== جدولة ========================
async def schedule_bakarah_prayers(application):
    prayer_times = IslamicCalendar.get_prayer_times()
    
    if not prayer_times:
        prayer_times = {'Fajr': '05:00', 'Dhuhr': '12:30', 'Asr': '15:45', 'Maghrib': '18:15', 'Isha': '19:45'}
    
    job_queue = application.job_queue
    
    for prayer_name, prayer_time in prayer_times.items():
        try:
            hour, minute = map(int, prayer_time.split(':'))
            minute += 5
            if minute >= 60:
                minute -= 60
                hour += 1
            if hour >= 24:
                hour -= 24
            
            time_obj = datetime.strptime(f'{hour:02d}:{minute:02d}', '%H:%M').time()
            job_queue.run_daily(callback=lambda c, p=prayer_name: send_bakarah_part(c, p), time=time_obj, name=f'bakarah_{prayer_name}')
        except:
            pass

async def schedule_user_quran_times(application):
    users = db.get_all_users()
    job_queue = application.job_queue
    
    for user in users:
        user_id = user[0]
        quran_time = user[10] if len(user) > 10 else '09:00'
        
        try:
            time_obj = datetime.strptime(quran_time, '%H:%M').time()
            job_queue.run_daily(lambda c, uid=user_id: send_daily_wird_single(c, uid), time=time_obj, name=f'daily_wird_{user_id}')
        except:
            pass

async def post_init(application: Application) -> None:
    await schedule_bakarah_prayers(application)
    await schedule_user_quran_times(application)

def setup_jobs(application):
    job_queue = application.job_queue
    
    if job_queue is None:
        logger.error("❌ JobQueue غير متاح")
        return
    
    job_queue.run_daily(send_morning_azkar, time=datetime.strptime('06:00', '%H:%M').time(), name='morning_azkar')
    job_queue.run_daily(send_evening_azkar, time=datetime.strptime('17:00', '%H:%M').time(), name='evening_azkar')
    job_queue.run_daily(send_mulk, time=datetime.strptime('22:00', '%H:%M').time(), name='mulk')
    job_queue.run_daily(send_friday_kahf, time=datetime.strptime('08:00', '%H:%M').time(), name='friday_kahf')
    job_queue.run_daily(check_islamic_occasions_daily, time=datetime.strptime('07:00', '%H:%M').time(), name='occasions')
    job_queue.run_daily(send_white_days_reminder, time=datetime.strptime('20:00', '%H:%M').time(), name='white_days')
    job_queue.run_daily(send_qiyam_reminder, time=datetime.strptime('02:00', '%H:%M').time(), name='qiyam')
    
    random_time_1 = datetime.strptime(f'{random.randint(10, 11)}:{random.randint(0, 59):02d}', '%H:%M').time()
    job_queue.run_daily(send_random_dhikr, time=random_time_1, name='random_dhikr_1')
    
    random_time_2 = datetime.strptime(f'{random.randint(15, 16)}:{random.randint(0, 59):02d}', '%H:%M').time()
    job_queue.run_daily(send_random_dhikr, time=random_time_2, name='random_dhikr_2')
    
    logger.info("✅ تم إعداد المهام")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
ℹ️ *وِرْدُ المُسْلِم*

/start - البدء

*المميزات:*
📖 الورد اليومي (وقت مخصص)
📗 سورة البقرة (12 صفحة)
☀️ أذكار الصباح والمساء
🌙 سورة الملك
🕋 سورة الكهف (الجمعة)
⚪ الأيام البيض
📅 المناسبات الإسلامية
🤲 أذكار متنوعة

*للمجموعات والقنوات:*
أضف البوت وسيعمل تلقائياً

🤲 بارك الله فيك
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

def main():
    print("=" * 60)
    print("🕌 وِرْدُ المُسْلِم ")
    print("=" * 60)
    
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n❌ ضع التوكن في BOT_TOKEN")
        return
    
    try:
        application = Application.builder().token(BOT_TOKEN).build()
    except Exception as e:
        print(f"\n❌ خطأ: {e}")
        return
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(ChatMemberHandler(track_bot_added, ChatMemberHandler.MY_CHAT_MEMBER))
    
    application.post_init = post_init
    setup_jobs(application)
    
    print("\n🚀 البوت يعمل")
    print("✨ جاهز")
    print("=" * 60 + "\n")
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        print("\n🛑 توقف")
    except Exception as e:
        print(f"\n❌ {e}")

if __name__ == '__main__':
    main()
