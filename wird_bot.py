import os
import asyncio
import logging
import sqlite3
import requests
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
    ChatMemberHandler,
    ConversationHandler,
    MessageHandler,
    filters
)
from telegram.constants import ChatMemberStatus

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# استخدام متغير بيئة للتوكن (مهم لـ Render)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
PORT = int(os.environ.get("PORT", 8443))

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

# حالات المحادثة
SELECTING_CITY = 1

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
                kahf_enabled BOOLEAN DEFAULT 1,
                mulk_enabled BOOLEAN DEFAULT 1,
                quran_time TEXT DEFAULT '09:00',
                current_page INTEGER DEFAULT 1,
                white_days_reminder BOOLEAN DEFAULT 1,
                city TEXT DEFAULT 'Makkah',
                country TEXT DEFAULT 'Saudi Arabia',
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
            'city': 'TEXT DEFAULT "Makkah"',
            'country': 'TEXT DEFAULT "Saudi Arabia"',
            'timezone_offset': 'INTEGER DEFAULT 3',
            'white_days_reminder': 'BOOLEAN DEFAULT 1'
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

# ======================== المدن المتاحة ========================
CITIES = {
    '🇸🇦 مكة المكرمة': ('Makkah', 'Saudi Arabia', 3),
    '🇸🇦 المدينة المنورة': ('Madinah', 'Saudi Arabia', 3),
    '🇸🇦 الرياض': ('Riyadh', 'Saudi Arabia', 3),
    '🇸🇦 جدة': ('Jeddah', 'Saudi Arabia', 3),
    '🇦🇪 دبي': ('Dubai', 'United Arab Emirates', 4),
    '🇦🇪 أبوظبي': ('Abu Dhabi', 'United Arab Emirates', 4),
    '🇪🇬 القاهرة': ('Cairo', 'Egypt', 2),
    '🇪🇬 الإسكندرية': ('Alexandria', 'Egypt', 2),
    '🇯🇴 عمّان': ('Amman', 'Jordan', 3),
    '🇰🇼 الكويت': ('Kuwait City', 'Kuwait', 3),
    '🇶🇦 الدوحة': ('Doha', 'Qatar', 3),
    '🇧🇭 المنامة': ('Manama', 'Bahrain', 3),
    '🇴🇲 مسقط': ('Muscat', 'Oman', 4),
    '🇾🇪 صنعاء': ('Sanaa', 'Yemen', 3),
    '🇸🇾 دمشق': ('Damascus', 'Syria', 3),
    '🇱🇧 بيروت': ('Beirut', 'Lebanon', 3),
    '🇮🇶 بغداد': ('Baghdad', 'Iraq', 3),
    '🇵🇸 القدس': ('Jerusalem', 'Palestine', 3),
    '🇱🇾 طرابلس': ('Tripoli', 'Libya', 2),
    '🇹🇳 تونس': ('Tunis', 'Tunisia', 1),
    '🇩🇿 الجزائر': ('Algiers', 'Algeria', 1),
    '🇲🇦 الرباط': ('Rabat', 'Morocco', 1),
}

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
            (1, 10): "🕌 يوم عاشوراء\n\nعن ابن عباس رضي الله عنهما: \"ما رأيت النبي ﷺ يتحرى صيام يوم فضله على غيره إلا هذا اليوم، يوم عاشوراء\"",
            (9, 1): "🌙 أول يوم رمضان\n\n﴿شَهْرُ رَمَضَانَ الَّذِي أُنزِلَ فِيهِ الْقُرْآنُ﴾",
            (9, 27): "🌙 ليلة القدر\n\n﴿لَيْلَةُ الْقَدْرِ خَيْرٌ مِّنْ أَلْفِ شَهْرٍ﴾",
            (10, 1): "🎉 أول يوم من عيد الفطر المبارك\n\nتقبل الله منا ومنكم",
            (10, 9): "🕋 يوم عرفة\n\nعن النبي ﷺ: \"ما من يوم أكثر من أن يعتق الله فيه عبدًا من النار من يوم عرفة\"",
            (10, 10): "🎊 عيد الأضحى\n\n كل عام وأنتم بخير، تقبل الله طاعتكم"
        }
        
        if day in [13, 14, 15]:
            return f"⚪ الأيام البيض ({day} {hijri['month_name']})\n\nعنْ أَبي ذَرٍّ رضي الله عنه، قَالَ: قالَ رسولُ اللَّهِ ﷺ: ( إِذا صُمْتَ مِنَ الشَّهْرِ ثَلاثًا، فَصُمْ ثَلاثَ عَشْرَةَ، وَأَرْبعَ عَشْرَةَ، وخَمْسَ عَشْرَةَ ) رواه الترمِذيُّ "
        
        return occasions.get((month, day))
    
    @staticmethod
    def is_day_before_white_days():
        hijri = IslamicCalendar.get_hijri_date()
        return hijri and hijri['day'] == 12

# ======================== محتوى الأذكار ========================
class IslamicContent:
    MORNING_AZKAR = """☀️ *أذكار الصباح*

﴿فَاذْكُرُونِي أَذْكُرْكُمْ وَاشْكُرُوا لِي وَلَا تَكْفُرُونِ﴾

قال رسول الله ﷺ: "من قال حين يصبح: أصبحنا وأصبح الملك لله، كتب الله له بها عشر حسنات"
"""

    EVENING_AZKAR = """🌙 *أذكار المساء*

﴿وَاذْكُر رَّبَّكَ فِي نَفْسِكَ تَضَرُّعًا وَخِيفَةً﴾

عن النبي ﷺ: "من قال حين يمسي: أمسينا وأمسى الملك لله، لم يزل في ذمة الله حتى يصبح"
"""

    MULK_REMINDER = """🌙 *سورة الملك*

﴿تَبَارَكَ الَّذِي بِيَدِهِ الْمُلْكُ وَهُوَ عَلَىٰ كُلِّ شَيْءٍ قَدِيرٌ﴾

عن أبي هريرة رضي الله عنه قال: قال رسول الله ﷺ: "إن سورة من القرآن ثلاثون آية شفعت لرجل حتى غُفر له، وهي سورة تبارك الذي بيده الملك"

🕌 طابت ليلتك بذكر الله
"""

    KAHF_FRIDAY = """🕌 *يوم الجمعة المبارك*

📖 سورة الكهف

﴿الْحَمْدُ لِلَّهِ الَّذِي أَنزَلَ عَلَىٰ عَبْدِهِ الْكِتَابَ وَلَمْ يَجْعَل لَّهُ عِوَجًا﴾

عن أبي سعيد الخدري رضي الله عنه قال: قال النبي ﷺ: "من قرأ سورة الكهف في يوم الجمعة أضاء له من النور ما بين الجمعتين"

💚 *الصلاة على النبي ﷺ*

عن أوس بن أوس رضي الله عنه قال: قال رسول الله ﷺ: "إن من أفضل أيامكم يوم الجمعة، فأكثروا علي من الصلاة فيه"

اللهم صل وسلم وبارك على سيدنا محمد وعلى آله وصحبه أجمعين

🤲 جمعة مباركة
"""

    QIYAM_REMINDER = """🌙 *قيام الليل والوتر*

عن أبي هريرة رضي الله عنه أن رسول الله ﷺ قال: "ينزل ربنا تبارك وتعالى كل ليلة إلى السماء الدنيا حين يبقى ثلث الليل الآخر، فيقول: من يدعوني فأستجيب له، من يسألني فأعطيه، من يستغفرني فأغفر له"

🤲 *دعاء قيام الليل:*

اللهم لك الحمد أنت نور السماوات والأرض، ولك الحمد أنت قيم السماوات والأرض، ولك الحمد أنت رب السماوات والأرض ومن فيهن

✨ بارك الله في قيامك
"""

    TASBIH_TYPES = [
        """📿 *تسبيح*

🔹 سبحان الله (33 مرة)
🔹 الحمد لله (33 مرة)
🔹 الله أكبر (34 مرة)

عن أبي هريرة رضي الله عنه قال: قال رسول الله ﷺ: "من سبح الله في دبر كل صلاة ثلاثًا وثلاثين، وحمد الله ثلاثًا وثلاثين، وكبر الله ثلاثًا وثلاثين... غُفرت خطاياه وإن كانت مثل زبد البحر"
""",
        """📿 *تسبيح*

🔹 سبحان الله وبحمده (100 مرة)

عن أبي هريرة رضي الله عنه قال: قال رسول الله ﷺ: "من قال: سبحان الله وبحمده، في يوم مئة مرة، حُطت خطاياه وإن كانت مثل زبد البحر"
""",
        """💎 *لا حول ولا قوة إلا بالله*

عن أبي موسى الأشعري رضي الله عنه قال: قال لي رسول الله ﷺ: "ألا أدلك على كنز من كنوز الجنة؟" فقلت: بلى يا رسول الله، قال: "لا حول ولا قوة إلا بالله"
""",
        """🤲 *استغفار*

🔹 أستغفر الله العظيم الذي لا إله إلا هو الحي القيوم وأتوب إليه

عن بلال بن يسار رضي الله عنه قال: قال رسول الله ﷺ: "من قال: أستغفر الله العظيم الذي لا إله إلا هو الحي القيوم وأتوب إليه، غُفر له وإن كان فرّ من الزحف"
""",
        """💚 *الصلاة على النبي ﷺ*

🔹 اللهم صل وسلم وبارك على سيدنا محمد

عن أبي هريرة رضي الله عنه قال: قال رسول الله ﷺ: "من صلى علي واحدة صلى الله عليه عشرًا"
"""
    ]
    
    @staticmethod
    def get_random_dhikr():
        return random.choice(IslamicContent.TASBIH_TYPES)

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

# ======================== اختيار المدينة ========================
async def ask_city_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """طلب اختيار المدينة"""
    keyboard = []
    cities_list = list(CITIES.keys())
    
    # ترتيب الأزرار في صفوف (3 أزرار في كل صف)
    for i in range(0, len(cities_list), 2):
        row = [InlineKeyboardButton(city, callback_data=f'city_{i+j}') 
               for j, city in enumerate(cities_list[i:i+2])]
        keyboard.append(row)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = """🌍 *اختر مدينتك*

لضبط مواقيت الصلاة والتذكيرات حسب موقعك
"""
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    return SELECTING_CITY

async def city_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيار المدينة"""
    query = update.callback_query
    await query.answer()
    
    city_index = int(query.data.split('_')[1])
    city_name = list(CITIES.keys())[city_index]
    city, country, tz = CITIES[city_name]
    
    user_id = query.from_user.id
    db.update_user_setting(user_id, 'city', city)
    db.update_user_setting(user_id, 'country', country)
    db.update_user_setting(user_id, 'timezone_offset', tz)
    
    await query.edit_message_text(
        f"✅ تم ضبط المدينة: {city_name}\n\n🕌 مرحباً بك في *وِرْدُ المُسْلِم*",
        parse_mode='Markdown'
    )
    
    await asyncio.sleep(1)
    await show_main_menu(update, context)
    
    return ConversationHandler.END

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض القائمة الرئيسية"""
    keyboard = [
        [InlineKeyboardButton("⚙️ إعداداتي", callback_data='settings')],
        [InlineKeyboardButton("📖 الورد اليومي", callback_data='daily_wird')],
        [InlineKeyboardButton("📿 أذكار سريعة", callback_data='quick_azkar')],
        [InlineKeyboardButton("ℹ️ المساعدة", callback_data='help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = """السلام عليكم ورحمة الله وبركاته 🌙

*وِرْدُ المُسْلِم*

📚 سأساعدك في:
• قراءة الورد اليومي
• التذكير بالأذكار
• المناسبات الإسلامية

اضغط الأزرار أدناه 👇
"""
    
    if update.callback_query:
        await update.callback_query.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

# ======================== معالج إضافة البوت للمجموعات ========================
async def track_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تشغيل تلقائي عند إضافة البوت"""
    result = update.my_chat_member
    if result is None:
        return
    
    new_status = result.new_chat_member.status
    chat = result.chat
    
    if new_status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR]:
        db.add_user(chat.id, chat.id)
        
        welcome_message = """
السلام عليكم ورحمة الله وبركاته 🌙

تم تفعيل *وِرْدُ المُسْلِم*

📚 سيتم إرسال:
• الورد اليومي
• أذكار الصباح والمساء
• سورة الكهف (الجمعة)
• المناسبات الإسلامية

🕌 بارك الله فيكم
        """
        
        try:
            await context.bot.send_message(chat_id=chat.id, text=welcome_message, parse_mode='Markdown')
        except:
            pass

# ======================== وظائف البوت ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء البوت"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    
    db.add_user(user.id, chat_id)
    
    # التحقق من وجود مدينة محفوظة
    user_data = db.get_user(user.id)
    
    if not user_data or (len(user_data) > 11 and not user_data[11]):
        # لم يختر مدينة بعد
        return await ask_city_selection(update, context)
    
    # عرض القائمة الرئيسية
    if chat_type in ['group', 'supergroup', 'channel']:
        welcome_message = """
السلام عليكم 🌙

*وِرْدُ المُسْلِم*

📚 التذكيرات:
• الورد اليومي
• أذكار الصباح والمساء
• سورة الكهف (الجمعة)
•  المناسبات الإسلامية

🕌 بارك الله فيكم
        """
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
    else:
        await show_main_menu(update, context)

async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """قائمة الإعدادات"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📖 عدد الصفحات", callback_data='set_pages')],
        [InlineKeyboardButton("⏰ وقت الورد", callback_data='set_quran_time')],
        [InlineKeyboardButton("🌍 المدينة", callback_data='set_city')],
        [InlineKeyboardButton("📗 سورة البقرة", callback_data='set_bakarah')],
        [InlineKeyboardButton("🔔 التنبيهات", callback_data='set_notifications')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='back_main')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("⚙️ *الإعدادات*", reply_markup=reply_markup, parse_mode='Markdown')

async def set_daily_pages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين عدد الصفحات"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("1", callback_data='pages_1'), InlineKeyboardButton("2", callback_data='pages_2'), InlineKeyboardButton("3", callback_data='pages_3')],
        [InlineKeyboardButton("5", callback_data='pages_5'), InlineKeyboardButton("10", callback_data='pages_10'), InlineKeyboardButton("20", callback_data='pages_20')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("📖 *عدد الصفحات*", reply_markup=reply_markup, parse_mode='Markdown')

async def set_quran_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين وقت الورد"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("05:00", callback_data='qtime_05:00'), InlineKeyboardButton("06:00", callback_data='qtime_06:00'), InlineKeyboardButton("07:00", callback_data='qtime_07:00')],
        [InlineKeyboardButton("08:00", callback_data='qtime_08:00'), InlineKeyboardButton("09:00", callback_data='qtime_09:00'), InlineKeyboardButton("10:00", callback_data='qtime_10:00')],
        [InlineKeyboardButton("20:00", callback_data='qtime_20:00'), InlineKeyboardButton("21:00", callback_data='qtime_21:00'), InlineKeyboardButton("22:00", callback_data='qtime_22:00')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("⏰ *وقت الورد*", reply_markup=reply_markup, parse_mode='Markdown')

async def set_bakarah_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إعدادات سورة البقرة"""
    query = update.callback_query
    await query.answer()
    
    user = db.get_user(query.from_user.id)
    bakarah_status = "✅ مفعّلة" if user and len(user) > 3 and user[3] else "❌ معطّلة"
    
    keyboard = [
        [InlineKeyboardButton("تفعيل ✅" if not (user and len(user) > 3 and user[3]) else "تعطيل ❌", callback_data='toggle_bakarah')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(f"📗 *سورة البقرة*\n\n{bakarah_status}\n\n12 صفحة على 5 صلوات", reply_markup=reply_markup, parse_mode='Markdown')

async def set_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إعدادات التنبيهات"""
    query = update.callback_query
    await query.answer()
    
    user = db.get_user(query.from_user.id)
    
    kahf = user[6] if user and len(user) > 6 else 1
    mulk = user[7] if user and len(user) > 7 else 1
    white = user[10] if user and len(user) > 10 else 1
    
    keyboard = [
        [InlineKeyboardButton(f"{'✅' if kahf else '❌'} سورة الكهف", callback_data='toggle_kahf')],
        [InlineKeyboardButton(f"{'✅' if mulk else '❌'} سورة الملك", callback_data='toggle_mulk')],
        [InlineKeyboardButton(f"{'✅' if white else '❌'} الأيام البيض", callback_data='toggle_white_days')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='settings')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("🔔 *التنبيهات*", reply_markup=reply_markup, parse_mode='Markdown')

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الأزرار"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    if data == 'back_main':
        await show_main_menu(update, context)
    elif data == 'settings':
        await settings_menu(update, context)
    elif data == 'set_pages':
        await set_daily_pages(update, context)
    elif data == 'set_quran_time':
        await set_quran_time(update, context)
    elif data == 'set_city':
        await ask_city_selection(update, context)
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
        await query.edit_message_text(f"✅ الوقت: {time_str}", parse_mode='Markdown')
        await asyncio.sleep(1)
        await settings_menu(update, context)
    elif data == 'toggle_bakarah':
        user = db.get_user(user_id)
        current = user[3] if user and len(user) > 3 else 0
        db.update_user_setting(user_id, 'bakarah_enabled', 0 if current else 1)
        await set_bakarah_setting(update, context)
    elif data == 'toggle_kahf':
        user = db.get_user(user_id)
        current = user[6] if user and len(user) > 6 else 1
        db.update_user_setting(user_id, 'kahf_enabled', 0 if current else 1)
        await set_notifications(update, context)
    elif data == 'toggle_mulk':
        user = db.get_user(user_id)
        current = user[7] if user and len(user) > 7 else 1
        db.update_user_setting(user_id, 'mulk_enabled', 0 if current else 1)
        await set_notifications(update, context)
    elif data == 'toggle_white_days':
        user = db.get_user(user_id)
        current = user[10] if user and len(user) > 10 else 1
        db.update_user_setting(user_id, 'white_days_reminder', 0 if current else 1)
        await set_notifications(update, context)
    elif data == 'daily_wird':
        user = db.get_user(user_id)
        if user:
            pages = user[2] if len(user) > 2 else 2
            quran_time = user[8] if len(user) > 8 else '13:00'
            await query.edit_message_text(f"📖 *وردك*\n\nالصفحات: {pages}\nالوقت: {quran_time}", parse_mode='Markdown')
    elif data == 'quick_azkar':
        keyboard = [
            [InlineKeyboardButton("📿 ذكر", callback_data='random_dhikr')],
            [InlineKeyboardButton("🔙 رجوع", callback_data='back_main')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("📿 *أذكار*", reply_markup=reply_markup, parse_mode='Markdown')
    elif data == 'random_dhikr':
        await query.edit_message_text(IslamicContent.get_random_dhikr(), parse_mode='Markdown')
    elif data == 'help':
        help_text = """ℹ️ *وِرْدُ المُسْلِم*

/start - البدء

*المميزات:*
📖 الورد اليومي
📗 سورة البقرة
☀️ أذكار الصباح والمساء
🌙 سورة الملك
🕋 سورة الكهف
⚪ الأيام البيض
📅 المناسبات الاسلامية

*للمجموعات:*
أضف البوت كأدمن وسيعمل تلقائياً

🤲 بارك الله فيك"""
        await query.edit_message_text(help_text, parse_mode='Markdown')

# ======================== المهام المجدولة ========================
async def send_morning_azkar(context: ContextTypes.DEFAULT_TYPE):
    users = db.get_all_users()
    image_path = MediaManager.get_morning_azkar_image()
    
    for user in users:
        morning_enabled = user[4] if len(user) > 4 else 1
        if morning_enabled:
            try:
                if image_path:
                    with open(image_path, 'rb') as photo:
                        await context.bot.send_photo(chat_id=user[1], photo=photo, caption=IslamicContent.MORNING_AZKAR, parse_mode='Markdown')
                else:
                    await context.bot.send_message(chat_id=user[1], text=IslamicContent.MORNING_AZKAR, parse_mode='Markdown')
            except:
                pass

async def send_evening_azkar(context: ContextTypes.DEFAULT_TYPE):
    users = db.get_all_users()
    image_path = MediaManager.get_evening_azkar_image()
    
    for user in users:
        evening_enabled = user[5] if len(user) > 5 else 1
        if evening_enabled:
            try:
                if image_path:
                    with open(image_path, 'rb') as photo:
                        await context.bot.send_photo(chat_id=user[1], photo=photo, caption=IslamicContent.EVENING_AZKAR, parse_mode='Markdown')
                else:
                    await context.bot.send_message(chat_id=user[1], text=IslamicContent.EVENING_AZKAR, parse_mode='Markdown')
            except:
                pass

async def send_daily_wird_single(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    user = db.get_user(user_id)
    if not user:
        return
    
    try:
        pages = user[2] if len(user) > 2 else 2
        current_page = user[9] if len(user) > 9 else 1
        
        end_page = current_page + pages - 1
        if end_page > QURAN_PAGES:
            end_page = QURAN_PAGES
            current_page = 1
        
        caption = f"""📖 *الورد اليومي*

﴿إِنَّ الَّذِينَ يَتْلُونَ كِتَابَ اللَّهِ وَأَقَامُوا الصَّلَاةَ وَأَنفَقُوا مِمَّا رَزَقْنَاهُمْ سِرًّا وَعَلَانِيَةً يَرْجُونَ تِجَارَةً لَّن تَبُورَ﴾

الصفحات: {current_page} - {end_page}"""
        
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
        
        if end_page - current_page >= 10:
            for page_num in range(current_page + 10, end_page + 1):
                image_path = MediaManager.get_quran_page_image(page_num)
                if image_path:
                    with open(image_path, 'rb') as photo:
                        await context.bot.send_photo(chat_id=user[1], photo=photo)
                    await asyncio.sleep(0.3)
        
        next_page = end_page + 1 if end_page < QURAN_PAGES else 1
        db.update_current_page(user[0], next_page)
    except:
        pass

async def send_mulk(context: ContextTypes.DEFAULT_TYPE):
    users = db.get_all_users()
    image_path = MediaManager.get_mulk_image()
    
    for user in users:
        mulk_enabled = user[7] if len(user) > 7 else 1
        if mulk_enabled:
            try:
                if image_path:
                    with open(image_path, 'rb') as photo:
                        await context.bot.send_photo(chat_id=user[1], photo=photo, caption=IslamicContent.MULK_REMINDER, parse_mode='Markdown')
                else:
                    await context.bot.send_message(chat_id=user[1], text=IslamicContent.MULK_REMINDER, parse_mode='Markdown')
            except:
                pass

async def send_friday_kahf(context: ContextTypes.DEFAULT_TYPE):
    if datetime.now().weekday() == 4:
        users = db.get_all_users()
        pdf_path = MediaManager.get_kahf_pdf()
        
        for user in users:
            kahf_enabled = user[6] if len(user) > 6 else 1
            if kahf_enabled:
                try:
                    if pdf_path:
                        with open(pdf_path, 'rb') as document:
                            await context.bot.send_document(chat_id=user[1], document=document, caption=IslamicContent.KAHF_FRIDAY, parse_mode='Markdown', filename="سورة_الكهف.pdf")
                    else:
                        await context.bot.send_message(chat_id=user[1], text=IslamicContent.KAHF_FRIDAY, parse_mode='Markdown')
                except:
                    pass

async def send_bakarah_part(context: ContextTypes.DEFAULT_TYPE, prayer_name: str):
    users = db.get_all_users()
    
    parts = {'Fajr': (1, 3), 'Dhuhr': (4, 6), 'Asr': (7, 9), 'Maghrib': (10, 10), 'Isha': (11, 12)}
    
    if prayer_name not in parts:
        return
    
    start_page, end_page = parts[prayer_name]
    images = MediaManager.get_bakarah_qiyam_images(start_page, end_page)
    
    prayers_ar = {'Fajr': 'الفجر', 'Dhuhr': 'الظهر', 'Asr': 'العصر', 'Maghrib': 'المغرب', 'Isha': 'العشاء'}
    caption = f"""📗 *سورة البقرة - مصحف القيام*

بعد صلاة {prayers_ar[prayer_name]}

﴿وَإِذَا سَأَلَكَ عِبَادِي عَنِّي فَإِنِّي قَرِيبٌ ۖ أُجِيبُ دَعْوَةَ الدَّاعِ إِذَا دَعَانِ﴾

صفحات {start_page}-{end_page}"""
    
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
            message = f"🌙 *مناسبة إسلامية*\n\n📅 {hijri['day']} {hijri['month_name']} {hijri['year']}هـ\n\n{occasion}"
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
            message = f"""⚪ *تذكير: الأيام البيض*

غدًا يبدأ صيام الأيام البيض من شهر {hijri['month_name']}

الأيام: 13، 14، 15

عن أبي ذر رضي الله عنه: أمرنا رسول الله ﷺ أن نصوم من الشهر ثلاثة أيام البيض: ثلاث عشرة وأربع عشرة وخمس عشرة

🤲 بارك الله في صيامك"""
            
            for user in users:
                white_enabled = user[10] if len(user) > 10 else 1
                if white_enabled:
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
    
    for user in users:
        try:
            await context.bot.send_message(chat_id=user[1], text=IslamicContent.QIYAM_REMINDER, parse_mode='Markdown')
        except:
            pass

# ======================== الجدولة ========================
async def schedule_bakarah_prayers(application):
    users = db.get_all_users()
    if not users:
        return
    
    user = users[0]
    city = user[11] if len(user) > 11 else 'Makkah'
    country = user[12] if len(user) > 12 else 'Saudi Arabia'
    
    prayer_times = IslamicCalendar.get_prayer_times(city, country)
    
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
        quran_time = user[8] if len(user) > 8 else '09:00'
        
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
        return
    
    job_queue.run_daily(send_morning_azkar, time=datetime.strptime('06:00', '%H:%M').time())
    job_queue.run_daily(send_evening_azkar, time=datetime.strptime('17:00', '%H:%M').time())
    job_queue.run_daily(send_mulk, time=datetime.strptime('22:00', '%H:%M').time())
    job_queue.run_daily(send_friday_kahf, time=datetime.strptime('10:00', '%H:%M').time())
    job_queue.run_daily(check_islamic_occasions_daily, time=datetime.strptime('07:00', '%H:%M').time())
    job_queue.run_daily(send_white_days_reminder, time=datetime.strptime('20:00', '%H:%M').time())
    job_queue.run_daily(send_qiyam_reminder, time=datetime.strptime('02:00', '%H:%M').time())
    
    job_queue.run_daily(send_random_dhikr, time=datetime.strptime(f'{random.randint(10, 11)}:{random.randint(0, 59):02d}', '%H:%M').time())
    job_queue.run_daily(send_random_dhikr, time=datetime.strptime(f'{random.randint(15, 16)}:{random.randint(0, 59):02d}', '%H:%M').time())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("""ℹ️ *وِرْدُ المُسْلِم*

/start - البدء

📖 الورد اليومي
📗 سورة البقرة
☀️ أذكار واستغفار
🕋 سورة الكهف
📅 المناسبات

🤲 بارك الله فيك""", parse_mode='Markdown')

def main():
    print("=" * 60)
    print("🕌 وِرْدُ المُسْلِم")
    print("=" * 60)
    
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n❌ ضع التوكن")
        return
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={SELECTING_CITY: [CallbackQueryHandler(city_selected, pattern=r'^city_\d+') ]},
        fallbacks=[CommandHandler('start', start)],
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(ChatMemberHandler(track_bot_added, ChatMemberHandler.MY_CHAT_MEMBER))
    
    application.post_init = post_init
    setup_jobs(application)
    
    print("\n🚀 البوت يعمل")
    print("=" * 60 + "\n")
    
    # لـ Render - استخدام webhook
    if os.environ.get("RENDER"):
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"https://your-app.onrender.com/{BOT_TOKEN}"
        )
    else:
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()