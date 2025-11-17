import asyncio
import logging
import sqlite3
import requests
import random
from datetime import datetime, timedelta, time as dt_time
from pathlib import Path
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

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
                ayat_kursi_enabled BOOLEAN DEFAULT 1,
                mulk_enabled BOOLEAN DEFAULT 1,
                quran_time TEXT DEFAULT '09:00',
                current_page INTEGER DEFAULT 1,
                white_days_reminder BOOLEAN DEFAULT 1,
                muawwidat_enabled BOOLEAN DEFAULT 1,
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
            'muawwidat_enabled': 'BOOLEAN DEFAULT 1'
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
            (1, 1): "🌙 رأس السنة الهجرية - عام هجري مبارك!",
            (1, 10): "🕌 صيام يوم عاشوراء - صيام مستحب",
            (9, 1): "🌙 أول يوم من رمضان المبارك",
            (9, 27): "⭐ ليلة القدر - ليلة مباركة",
            (10, 1): "🎉 عيد الفطر المبارك",
            (10, 9): "🕋 يوم عرفة",
            (10, 10): "🎊 عيد الأضحى المبارك",
            (12, 10): "🕋 يوم التروية"
        }
        
        if day in [13, 14, 15]:
            return f"⚪ اليوم من الأيام البيض ({day} {hijri['month_name']}) - صيام مستحب"
        
        return occasions.get((month, day))
    
    @staticmethod
    def is_day_before_white_days():
        hijri = IslamicCalendar.get_hijri_date()
        if not hijri:
            return False
        return hijri['day'] == 12

# ======================== محتوى الأذكار ========================
class IslamicContent:
    TASBIH_TYPES = [
        '''📿 *تسبيح*

🔹 سبحان الله (33)
🔹 الحمد لله (33)
🔹 الله أكبر (34)

"من سبح الله دبر كل صلاة ثلاثًا وثلاثين غُفرت خطاياه"''',
        '''📿 *تسبيح*

🔹 سبحان الله وبحمده (100 مرة)

"من قال: سبحان الله وبحمده، في يوم مئة مرة، حُطت خطاياه"''',
        '''📿 *تسبيح*

🔹 سبحان الله العظيم وبحمده

"من قال: سبحان الله العظيم وبحمده، غُرست له نخلة في الجنة"''',
        '''📿 *تسبيح*

🔹 سبحان الله والحمد لله ولا إله إلا الله والله أكبر

"أحب الكلام إلى الله أربع"''',
        '''📿 *تسبيح*

🔹 لا إله إلا الله وحده لا شريك له، له الملك وله الحمد وهو على كل شيء قدير (10 مرات)

"كان كمن أعتق أربعة أنفس من ولد إسماعيل"'''
    ]
    
    ISTIGHFAR_TYPES = [
        '''🤲 *استغفار*

🔹 أستغفر الله العظيم الذي لا إله إلا هو الحي القيوم وأتوب إليه (3 مرات)

من قالها غُفر له''',
        '''🤲 *سيد الاستغفار*

🔹 اللهم أنت ربي لا إله إلا أنت، خلقتني وأنا عبدك، وأنا على عهدك ووعدك ما استطعت، أعوذ بك من شر ما صنعت، أبوء لك بنعمتك علي وأبوء بذنبي، فاغفر لي فإنه لا يغفر الذنوب إلا أنت

"من قالها موقنًا بها فمات فهو من أهل الجنة"''',
        '''🤲 *استغفار*

🔹 أستغفر الله وأتوب إليه (100 مرة)

"إني لأستغفر الله في اليوم مئة مرة"''',
        '''🤲 *استغفار*

🔹 رب اغفر لي وتب علي إنك أنت التواب الرحيم (100 مرة)''',
        '''🤲 *استغفار*

🔹 اللهم اغفر لي ذنبي كله، دقه وجله، وأوله وآخره، وعلانيته وسره'''
    ]
    
    GENERAL_AZKAR = [
        '''💎 *ذكر*

🔹 لا حول ولا قوة إلا بالله

"كنز من كنوز الجنة"''',
        '''💎 *الباقيات الصالحات*

🔹 سبحان الله، والحمد لله، ولا إله إلا الله، والله أكبر''',
        '''💎 *الصلاة على النبي ﷺ*

🔹 اللهم صل وسلم وبارك على سيدنا محمد

"من صلى علي صلاة صلى الله عليه بها عشرًا"''',
        '''💎 *كلمتان خفيفتان*

🔹 سبحان الله وبحمده، سبحان الله العظيم

"خفيفتان على اللسان، ثقيلتان في الميزان"''',
        '''💎 *أفضل الذكر*

🔹 لا إله إلا الله

"أفضل الذكر: لا إله إلا الله"'''
    ]
    
    @staticmethod
    def get_random_tasbih():
        return random.choice(IslamicContent.TASBIH_TYPES)
    
    @staticmethod
    def get_random_istighfar():
        return random.choice(IslamicContent.ISTIGHFAR_TYPES)
    
    @staticmethod
    def get_random_dhikr():
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
    def get_ayat_kursi_image() -> Optional[Path]:
        for ext in ['jpg', 'png', 'jpeg']:
            image_file = AZKAR_PATH / f"ayat_kursi.{ext}"
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
    def get_muawwidat_image() -> Optional[Path]:
        for ext in ['jpg', 'png', 'jpeg']:
            image_file = AZKAR_PATH / f"muawwidat.{ext}"
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
        welcome_message = f"""
السلام عليكم ورحمة الله وبركاته 🌙

تم إضافة *بوت وِرْدُ المُسْلِم* للمجموعة

📚 سيتم إرسال التذكيرات التالية:
• الورد اليومي من القرآن (مع الصور)
• أذكار الصباح والمساء
• سورة الكهف كل جمعة 
• المعوذات بعد الفجر والمغرب
• سورة البقرة (مصحف القيام) - اختياري
• المناسبات الإسلامية
• أذكار متنوعة

🕌 بارك الله فيكم
        """
    else:
        welcome_message = f"""
السلام عليكم ورحمة الله وبركاته 🌙

أهلاً أخي/أختي {user.first_name}!

مرحبًا بك في *بوت وِرْدُ المُسْلِم* 

📚 سأساعدك في:
• قراءة وردك اليومي من القرآن
• تذكيرك بالأذكار في أوقاتها
• إرسال سورة الكهف كل جمعة
• تنبيهك بالمناسبات الإسلامية
• المعوذات في أوقاتها
• أذكار متنوعة

اضغط على الأزرار أدناه 👇
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
        [InlineKeyboardButton("📖 عدد صفحات الورد", callback_data='set_pages')],
        [InlineKeyboardButton("⏰ وقت الورد اليومي", callback_data='set_quran_time')],
        [InlineKeyboardButton("📗 سورة البقرة", callback_data='set_bakarah')],
        [InlineKeyboardButton("🔔 التنبيهات", callback_data='set_notifications')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='back_main')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "⚙️ *إعدادات البوت*\n\nاختر الإعداد:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def set_daily_pages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("1 صفحة", callback_data='pages_1'),
         InlineKeyboardButton("2 صفحة", callback_data='pages_2')],
        [InlineKeyboardButton("3 صفحات", callback_data='pages_3'),
         InlineKeyboardButton("5 صفحات", callback_data='pages_5')],
        [InlineKeyboardButton("10 صفحات", callback_data='pages_10'),
         InlineKeyboardButton("20 صفحة (جزء)", callback_data='pages_20')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "📖 *كم صفحة تريد أن تقرأ يوميًا؟*",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def set_quran_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("05:00 صباح", callback_data='qtime_05:00'),
         InlineKeyboardButton("06:00 صباح", callback_data='qtime_06:00')],
        [InlineKeyboardButton("07:00 صباح", callback_data='qtime_07:00'),
         InlineKeyboardButton("08:00 صباح", callback_data='qtime_08:00')],
        [InlineKeyboardButton("09:00 صباح", callback_data='qtime_09:00'),
         InlineKeyboardButton("10:00 صباح", callback_data='qtime_10:00')],
        [InlineKeyboardButton("08:00 مساء", callback_data='qtime_20:00'),
         InlineKeyboardButton("09:00 مساء", callback_data='qtime_21:00')],
        [InlineKeyboardButton("10:00 مساء", callback_data='qtime_22:00'),
         InlineKeyboardButton("11:00 مساء", callback_data='qtime_23:00')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    user = db.get_user(query.from_user.id)
    current_time = user[11] if user and len(user) > 11 else '09:00'
    
    await query.edit_message_text(
        f"⏰ *اختر وقت الورد اليومي*\n\nالوقت الحالي: {current_time}",
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
        f"""
📗 *سورة البقرة - مصحف القيام*

الحالة: {bakarah_status}

سيتم إرسال أجزاء من سورة البقرة بعد كل صلاة:
• بعد الفجر: صفحات 1-3
• بعد الظهر: صفحات 4-6
• بعد العصر: صفحات 7-9
• بعد المغرب: صفحة 10
• بعد العشاء: صفحات 11-12
        """,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def set_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = db.get_user(query.from_user.id)
    
    kahf_enabled = user[8] if user and len(user) > 8 else 1
    ayat_kursi_enabled = user[9] if user and len(user) > 9 else 1
    mulk_enabled = user[10] if user and len(user) > 10 else 1
    white_days_enabled = user[13] if user and len(user) > 13 else 1
    muawwidat_enabled = user[14] if user and len(user) > 14 else 1
    
    keyboard = [
        [InlineKeyboardButton(
            f"{'✅' if kahf_enabled else '❌'} سورة الكهف (الجمعة)", 
            callback_data='toggle_kahf'
        )],
        [InlineKeyboardButton(
            f"{'✅' if ayat_kursi_enabled else '❌'} آية الكرسي", 
            callback_data='toggle_ayat_kursi'
        )],
        [InlineKeyboardButton(
            f"{'✅' if mulk_enabled else '❌'} سورة الملك", 
            callback_data='toggle_mulk'
        )],
        [InlineKeyboardButton(
            f"{'✅' if muawwidat_enabled else '❌'} المعوذات", 
            callback_data='toggle_muawwidat'
        )],
        [InlineKeyboardButton(
            f"{'✅' if white_days_enabled else '❌'} تذكير الأيام البيض", 
            callback_data='toggle_white_days'
        )],
        [InlineKeyboardButton("🔙 رجوع", callback_data='settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🔔 *التنبيهات*\n\nاضغط لتفعيل/تعطيل:",
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
        await query.edit_message_text(
            "🏠 *القائمة الرئيسية*",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif data == 'settings':
        await settings_menu(update, context)
    
    elif data == 'set_pages':
        await set_daily_pages(update, context)
    
    elif data == 'set_quran_time':
        await set_quran_time(update, context)
    
    elif data == 'set_bakarah':
        await set_bakarah_setting(update, context)
    
    elif data == 'set_notifications':
        await set_notifications(update, context)
    
    elif data.startswith('pages_'):
        pages = int(data.split('_')[1])
        db.update_user_setting(user_id, 'daily_pages', pages)
        await query.edit_message_text(
            f"✅ تم تعيين الورد اليومي إلى {pages} صفحة",
            parse_mode='Markdown'
        )
        await asyncio.sleep(1.5)
        await settings_menu(update, context)
    
    elif data.startswith('qtime_'):
        time_str = data.split('_')[1]
        db.update_user_setting(user_id, 'quran_time', time_str)
        
        # إعادة جدولة الورد اليومي
        job_name = f'daily_wird_{user_id}'
        current_jobs = context.application.job_queue.get_jobs_by_name(job_name)
        for job in current_jobs:
            job.schedule_removal()
        
        context.application.job_queue.run_daily(
            lambda c: send_daily_wird_single(c, user_id),
            time=datetime.strptime(time_str, '%H:%M').time(),
            name=job_name
        )
        
        await query.edit_message_text(
            f"✅ تم تعيين وقت الورد اليومي: {time_str}",
            parse_mode='Markdown'
        )
        await asyncio.sleep(1.5)
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
    
    elif data == 'toggle_ayat_kursi':
        user = db.get_user(user_id)
        current_value = user[9] if user and len(user) > 9 else 1
        new_value = 0 if current_value else 1
        db.update_user_setting(user_id, 'ayat_kursi_enabled', new_value)
        await set_notifications(update, context)
    
    elif data == 'toggle_mulk':
        user = db.get_user(user_id)
        current_value = user[10] if user and len(user) > 10 else 1
        new_value = 0 if current_value else 1
        db.update_user_setting(user_id, 'mulk_enabled', new_value)
        await set_notifications(update, context)
    
    elif data == 'toggle_muawwidat':
        user = db.get_user(user_id)
        current_value = user[14] if user and len(user) > 14 else 1
        new_value = 0 if current_value else 1
        db.update_user_setting(user_id, 'muawwidat_enabled', new_value)
        await set_notifications(update, context)
    
    elif data == 'toggle_white_days':
        user = db.get_user(user_id)
        current_value = user[13] if user and len(user) > 13 else 1
        new_value = 0 if current_value else 1
        db.update_user_setting(user_id, 'white_days_reminder', new_value)
        await set_notifications(update, context)
    
    elif data == 'daily_wird':
        user = db.get_user(user_id)
        if user:
            pages = user[2] if len(user) > 2 else 2
            current_page = user[12] if len(user) > 12 else 1
            quran_time = user[11] if len(user) > 11 else '09:00'
            await query.edit_message_text(
                f"""
📖 *وردك اليومي*

عدد الصفحات: {pages} صفحة
الصفحة الحالية: {current_page}
الوقت: {quran_time}

سيتم إرسال وردك يوميًا مع صور الصفحات

🕌 بارك الله في أوقاتك
                """,
                parse_mode='Markdown'
            )
    
    elif data == 'quick_azkar':
        keyboard = [
            [InlineKeyboardButton("📿 آية الكرسي", callback_data='send_ayat_kursi')],
            [InlineKeyboardButton("📿 المعوذات", callback_data='send_muawwidat')],
            [InlineKeyboardButton("📿 تسبيح", callback_data='random_tasbih')],
            [InlineKeyboardButton("🤲 استغفار", callback_data='random_istighfar')],
            [InlineKeyboardButton("💎 ذكر", callback_data='random_dhikr')],
            [InlineKeyboardButton("🔙 رجوع", callback_data='back_main')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "📿 *أذكار سريعة*",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif data == 'send_ayat_kursi':
        image_path = MediaManager.get_ayat_kursi_image()
        caption = "🕌 *آية الكرسي*\n\n﴿اللَّهُ لَا إِلَٰهَ إِلَّا هُوَ الْحَيُّ الْقَيُّومُ﴾"
        
        if image_path:
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=open(image_path, 'rb'),
                caption=caption,
                parse_mode='Markdown'
            )
        else:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=caption,
                parse_mode='Markdown'
            )
    
    elif data == 'send_muawwidat':
        image_path = MediaManager.get_muawwidat_image()
        caption = "📿 *المعوذات*\n\n﴿قُلْ هُوَ اللَّهُ أَحَدٌ﴾\n﴿قُلْ أَعُوذُ بِرَبِّ الْفَلَقِ﴾\n﴿قُلْ أَعُوذُ بِرَبِّ النَّاسِ﴾"
        
        if image_path:
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=open(image_path, 'rb'),
                caption=caption,
                parse_mode='Markdown'
            )
        else:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=caption,
                parse_mode='Markdown'
            )
    
    elif data == 'random_tasbih':
        await query.edit_message_text(IslamicContent.get_random_tasbih(), parse_mode='Markdown')
    
    elif data == 'random_istighfar':
        await query.edit_message_text(IslamicContent.get_random_istighfar(), parse_mode='Markdown')
    
    elif data == 'random_dhikr':
        await query.edit_message_text(IslamicContent.get_random_dhikr(), parse_mode='Markdown')
    
    elif data == 'help':
        help_text = """
ℹ️ *مساعدة بوت وِرْدُ المُسْلِم*

*الأوامر:*
/start - بدء البوت

*المميزات:*
📖 الورد اليومي (مع تحديد الوقت)
📗 سورة البقرة (12 صفحة)
☀️ أذكار الصباح والمساء
📿 آية الكرسي والمعوذات
🌙 سورة الملك
🕋 سورة الكهف (الجمعة)
🤲 أذكار متنوعة
⚪ الأيام البيض
📅 المناسبات الإسلامية

*للمجموعات:*
يمكن إضافة البوت لمجموعات وقنوات
وسيرسل التذكيرات تلقائياً

🤲 بارك الله فيك
        """
        await query.edit_message_text(help_text, parse_mode='Markdown')

# ======================== المهام المجدولة ========================
async def send_morning_azkar(context: ContextTypes.DEFAULT_TYPE):
    users = db.get_all_users()
    image_path = MediaManager.get_morning_azkar_image()
    
    caption = "☀️ *أذكار الصباح*\n\nصباح الخير والبركة 🌅\n\n﴿فَاذْكُرُونِي أَذْكُرْكُمْ﴾"
    
    for user in users:
        morning_enabled = user[4] if len(user) > 4 else 1
        if morning_enabled:
            try:
                if image_path:
                    with open(image_path, 'rb') as photo:
                        await context.bot.send_photo(
                            chat_id=user[1],
                            photo=photo,
                            caption=caption,
                            parse_mode='Markdown'
                        )
                else:
                    await context.bot.send_message(
                        chat_id=user[1],
                        text=caption,
                        parse_mode='Markdown'
                    )
            except:
                pass

async def send_evening_azkar(context: ContextTypes.DEFAULT_TYPE):
    users = db.get_all_users()
    image_path = MediaManager.get_evening_azkar_image()
    
    caption = "🌙 *أذكار المساء*\n\nمساء الخير 🌆\n\n﴿وَاذْكُر رَّبَّكَ﴾"
    
    for user in users:
        evening_enabled = user[5] if len(user) > 5 else 1
        if evening_enabled:
            try:
                if image_path:
                    with open(image_path, 'rb') as photo:
                        await context.bot.send_photo(
                            chat_id=user[1],
                            photo=photo,
                            caption=caption,
                            parse_mode='Markdown'
                        )
                else:
                    await context.bot.send_message(
                        chat_id=user[1],
                        text=caption,
                        parse_mode='Markdown'
                    )
            except:
                pass

async def send_daily_wird_single(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    user = db.get_user(user_id)
    if not user:
        return
    
    try:
        pages = user[2] if len(user) > 2 else 2
        current_page = user[12] if len(user) > 12 else 1
        
        end_page = current_page + pages - 1
        if end_page > QURAN_PAGES:
            end_page = QURAN_PAGES
            current_page = 1
        
        caption = f"📖 *الورد اليومي*\n\n﴿إِنَّ الَّذِينَ يَتْلُونَ كِتَابَ اللَّهِ﴾\n\nالصفحات: {current_page} - {end_page}"
        
        await context.bot.send_message(
            chat_id=user[1],
            text=caption,
            parse_mode='Markdown'
        )
        
        for page_num in range(current_page, end_page + 1):
            image_path = MediaManager.get_quran_page_image(page_num)
            if image_path:
                with open(image_path, 'rb') as photo:
                    await context.bot.send_photo(
                        chat_id=user[1],
                        photo=photo,
                        caption=f"📖 صفحة {page_num}"
                    )
                await asyncio.sleep(0.5)
        
        next_page = end_page + 1
        if next_page > QURAN_PAGES:
            next_page = 1
        db.update_current_page(user[0], next_page)
    except:
        pass

async def send_ayat_kursi(context: ContextTypes.DEFAULT_TYPE):
    users = db.get_all_users()
    image_path = MediaManager.get_ayat_kursi_image()
    
    caption = "🕌 *آية الكرسي*\n\n﴿اللَّهُ لَا إِلَٰهَ إِلَّا هُوَ الْحَيُّ الْقَيُّومُ﴾"
    
    for user in users:
        ayat_kursi_enabled = user[9] if len(user) > 9 else 1
        if ayat_kursi_enabled:
            try:
                if image_path:
                    with open(image_path, 'rb') as photo:
                        await context.bot.send_photo(
                            chat_id=user[1],
                            photo=photo,
                            caption=caption,
                            parse_mode='Markdown'
                        )
                else:
                    await context.bot.send_message(
                        chat_id=user[1],
                        text=caption,
                        parse_mode='Markdown'
                    )
            except:
                pass

async def send_mulk(context: ContextTypes.DEFAULT_TYPE):
    users = db.get_all_users()
    image_path = MediaManager.get_mulk_image()
    
    caption = "🌙 *سورة الملك*\n\n﴿تَبَارَكَ الَّذِي بِيَدِهِ الْمُلْكُ﴾\n\nطابت ليلتك"
    
    for user in users:
        mulk_enabled = user[10] if len(user) > 10 else 1
        if mulk_enabled:
            try:
                if image_path:
                    with open(image_path, 'rb') as photo:
                        await context.bot.send_photo(
                            chat_id=user[1],
                            photo=photo,
                            caption=caption,
                            parse_mode='Markdown'
                        )
                else:
                    await context.bot.send_message(
                        chat_id=user[1],
                        text=caption,
                        parse_mode='Markdown'
                    )
            except:
                pass

async def send_muawwidat(context: ContextTypes.DEFAULT_TYPE, prayer_type: str = 'after_fajr'):
    users = db.get_all_users()
    image_path = MediaManager.get_muawwidat_image()
    
    if prayer_type == 'after_fajr':
        caption = "📿 *المعوذات - بعد الفجر*\n\n﴿قُلْ هُوَ اللَّهُ أَحَدٌ﴾\n﴿قُلْ أَعُوذُ بِرَبِّ الْفَلَقِ﴾\n﴿قُلْ أَعُوذُ بِرَبِّ النَّاسِ﴾\n\n(تُقرأ ثلاث مرات)"
    else:
        caption = "📿 *المعوذات - بعد المغرب*\n\n﴿قُلْ هُوَ اللَّهُ أَحَدٌ﴾\n﴿قُلْ أَعُوذُ بِرَبِّ الْفَلَقِ﴾\n﴿قُلْ أَعُوذُ بِرَبِّ النَّاسِ﴾\n\n(تُقرأ ثلاث مرات)"
    
    for user in users:
        muawwidat_enabled = user[14] if len(user) > 14 else 1
        if muawwidat_enabled:
            try:
                if image_path:
                    with open(image_path, 'rb') as photo:
                        await context.bot.send_photo(
                            chat_id=user[1],
                            photo=photo,
                            caption=caption,
                            parse_mode='Markdown'
                        )
                else:
                    await context.bot.send_message(
                        chat_id=user[1],
                        text=caption,
                        parse_mode='Markdown'
                    )
            except:
                pass

async def send_friday_kahf(context: ContextTypes.DEFAULT_TYPE):
    if datetime.now().weekday() == 4:
        users = db.get_all_users()
        pdf_path = MediaManager.get_kahf_pdf()
        
        caption = "🕌 *الجمعة*\n\n📖 سورة الكهف\n\n﴿الْحَمْدُ لِلَّهِ﴾\n\n💚 الصلاة على النبي ﷺ\n\nجمعة مباركة"
        
        for user in users:
            kahf_enabled = user[8] if len(user) > 8 else 1
            if kahf_enabled:
                try:
                    if pdf_path:
                        with open(pdf_path, 'rb') as document:
                            await context.bot.send_document(
                                chat_id=user[1],
                                document=document,
                                caption=caption,
                                parse_mode='Markdown',
                                filename="سورة_الكهف.pdf"
                            )
                    else:
                        await context.bot.send_message(
                            chat_id=user[1],
                            text=caption,
                            parse_mode='Markdown'
                        )
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
    
    prayers_ar = {
        'Fajr': 'الفجر',
        'Dhuhr': 'الظهر',
        'Asr': 'العصر',
        'Maghrib': 'المغرب',
        'Isha': 'العشاء'
    }
    
    caption = f"📗 *سورة البقرة*\n\nبعد {prayers_ar[prayer_name]}\n\nصفحات {start_page}-{end_page}"
    
    for user in users:
        bakarah_enabled = user[3] if len(user) > 3 else 0
        if bakarah_enabled:
            try:
                await context.bot.send_message(
                    chat_id=user[1],
                    text=caption,
                    parse_mode='Markdown'
                )
                
                for image_path in images:
                    with open(image_path, 'rb') as photo:
                        await context.bot.send_photo(
                            chat_id=user[1],
                            photo=photo
                        )
                    await asyncio.sleep(0.5)
            except:
                pass

async def check_islamic_occasions_daily(context: ContextTypes.DEFAULT_TYPE):
    occasion = IslamicCalendar.check_islamic_occasions()
    
    if occasion:
        users = db.get_all_users()
        hijri = IslamicCalendar.get_hijri_date()
        
        if hijri:
            message = f"🌙 *مناسبة إسلامية*\n\n📅 {hijri['day']} {hijri['month_name']} {hijri['year']}هـ\n\n{occasion}"
            
            for user in users:
                try:
                    await context.bot.send_message(
                        chat_id=user[1],
                        text=message,
                        parse_mode='Markdown'
                    )
                except:
                    pass

async def send_white_days_reminder(context: ContextTypes.DEFAULT_TYPE):
    if IslamicCalendar.is_day_before_white_days():
        users = db.get_all_users()
        hijri = IslamicCalendar.get_hijri_date()
        
        if hijri:
            message = f"⚪ *الأيام البيض*\n\nغدًا يبدأ صيام الأيام البيض من {hijri['month_name']}\n\nالأيام: 13، 14، 15\n\nبارك الله فيك"
            
            for user in users:
                white_days_enabled = user[13] if len(user) > 13 else 1
                if white_days_enabled:
                    try:
                        await context.bot.send_message(
                            chat_id=user[1],
                            text=message,
                            parse_mode='Markdown'
                        )
                    except:
                        pass

async def send_random_dhikr(context: ContextTypes.DEFAULT_TYPE):
    users = db.get_all_users()
    
    dhikr_type = random.choice(['tasbih', 'istighfar', 'general'])
    
    if dhikr_type == 'tasbih':
        message = IslamicContent.get_random_tasbih()
    elif dhikr_type == 'istighfar':
        message = IslamicContent.get_random_istighfar()
    else:
        message = IslamicContent.get_random_dhikr()
    
    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user[1],
                text=message,
                parse_mode='Markdown'
            )
        except:
            pass

async def send_qiyam_reminder(context: ContextTypes.DEFAULT_TYPE):
    users = db.get_all_users()
    
    message = """🌙 *قيام الليل*

"ينزل ربنا إلى السماء الدنيا حين يبقى ثلث الليل الآخر"

بارك الله في قيامك"""
    
    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user[1],
                text=message,
                parse_mode='Markdown'
            )
        except:
            pass

# ======================== جدولة سورة البقرة ========================
async def schedule_bakarah_prayers(application):
    prayer_times = IslamicCalendar.get_prayer_times()
    
    if not prayer_times:
        prayer_times = {
            'Fajr': '05:00',
            'Dhuhr': '12:30',
            'Asr': '15:45',
            'Maghrib': '18:15',
            'Isha': '19:45'
        }
    
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
            
            job_queue.run_daily(
                callback=lambda c, p=prayer_name: send_bakarah_part(c, p),
                time=time_obj,
                name=f'bakarah_{prayer_name}'
            )
            
            # جدولة المعوذات بعد الفجر والمغرب
            if prayer_name == 'Fajr':
                muawwidat_time = datetime.strptime(f'{hour:02d}:{minute:02d}', '%H:%M').time()
                job_queue.run_daily(
                    callback=lambda c: send_muawwidat(c, 'after_fajr'),
                    time=muawwidat_time,
                    name='muawwidat_fajr'
                )
            elif prayer_name == 'Maghrib':
                muawwidat_time = datetime.strptime(f'{hour:02d}:{minute:02d}', '%H:%M').time()
                job_queue.run_daily(
                    callback=lambda c: send_muawwidat(c, 'after_maghrib'),
                    time=muawwidat_time,
                    name='muawwidat_maghrib'
                )
        except:
            pass

async def schedule_user_quran_times(application):
    users = db.get_all_users()
    job_queue = application.job_queue
    
    for user in users:
        user_id = user[0]
        quran_time = user[11] if len(user) > 11 else '09:00'
        
        try:
            time_obj = datetime.strptime(quran_time, '%H:%M').time()
            job_queue.run_daily(
                lambda c, uid=user_id: send_daily_wird_single(c, uid),
                time=time_obj,
                name=f'daily_wird_{user_id}'
            )
        except:
            pass

async def post_init(application: Application) -> None:
    await schedule_bakarah_prayers(application)
    await schedule_user_quran_times(application)

# ======================== إعداد المهام ========================
def setup_jobs(application):
    job_queue = application.job_queue
    
    job_queue.run_daily(send_morning_azkar, time=datetime.strptime('06:00', '%H:%M').time(), name='morning_azkar')
    job_queue.run_daily(send_evening_azkar, time=datetime.strptime('17:00', '%H:%M').time(), name='evening_azkar')
    job_queue.run_daily(send_ayat_kursi, time=datetime.strptime('08:00', '%H:%M').time(), name='ayat_kursi')
    job_queue.run_daily(send_mulk, time=datetime.strptime('22:00', '%H:%M').time(), name='mulk')
    job_queue.run_daily(send_friday_kahf, time=datetime.strptime('13:00', '%H:%M').time(), name='friday_kahf')
    job_queue.run_daily(check_islamic_occasions_daily, time=datetime.strptime('07:00', '%H:%M').time(), name='occasions')
    job_queue.run_daily(send_white_days_reminder, time=datetime.strptime('20:00', '%H:%M').time(), name='white_days')
    job_queue.run_daily(send_qiyam_reminder, time=datetime.strptime('02:00', '%H:%M').time(), name='qiyam')
    
    random_time_1 = datetime.strptime(f'{random.randint(10, 11)}:{random.randint(0, 59):02d}', '%H:%M').time()
    job_queue.run_daily(send_random_dhikr, time=random_time_1, name='random_dhikr_1')
    
    random_time_2 = datetime.strptime(f'{random.randint(15, 16)}:{random.randint(0, 59):02d}', '%H:%M').time()
    job_queue.run_daily(send_random_dhikr, time=random_time_2, name='random_dhikr_2')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
ℹ️ *بوت وِرْدُ المُسْلِم*

/start - القائمة الرئيسية

*المميزات:*
📖 الورد اليومي (وقت قابل للتعديل)
📗 سورة البقرة بمصحف قيام (12 صفحة)
☀️ أذكار الصباح والمساء
📿 المعوذات 
🕌 آية الكرسي وسورة الملك
🕋 سورة الكهف (الجمعة)
⚪ الأيام البيض
📅 المناسبات الإسلامية

*للمجموعات والقنوات:*
أضف البوت وسيرسل التذكيرات تلقائياً

🤲 بارك الله فيك
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

# ======================== التشغيل ========================
def main():
    print("=" * 60)
    print("🕌 بوت وِرْدُ المُسْلِم")
    print("=" * 60)
    
    if BOT_TOKEN == "Put_Your_Bot_Token_Here":
        print("\n❌ ضع توكن البوت أولاً في BOT_TOKEN")
        return
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    application.post_init = post_init
    
    setup_jobs(application)
    
    print("\n🚀 البوت يعمل الآن...")
    print("✨ جاهز لاستقبال الرسائل")
    print("🔧 للإيقاف: Ctrl+C\n")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()