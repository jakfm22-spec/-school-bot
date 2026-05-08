"""
بوت مدرسة البتول الطاهرة (ع) القرآنية
النسخة المصححة - جاهزة للتشغيل
"""

import logging
import os
import random
import string
from datetime import datetime
from functools import wraps

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters
)
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.sql import func

# ==========================================
# الإعدادات الأساسية
# ==========================================
load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN', '')
OWNER_ID = int(os.getenv('OWNER_ID', 0))
DB_PATH = os.path.join(os.path.dirname(__file__), 'school_bot.db')

# إعداد السجل
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================
# قاعدة البيانات
# ==========================================
Base = declarative_base()
engine = create_engine(f'sqlite:///{DB_PATH}', connect_args={'check_same_thread': False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        return db
    finally:
        db.close()

# ==========================================
# النماذج (Models)
# ==========================================
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True)
    name = Column(String(255))
    username = Column(String(255))
    role = Column(String(50), default='user')
    is_banned = Column(Boolean, default=False)
    join_date = Column(DateTime, default=func.now())

class Ticket(Base):
    __tablename__ = 'tickets'
    id = Column(Integer, primary_key=True)
    ticket_number = Column(String(50), unique=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    type = Column(String(50))
    category = Column(String(100))
    content = Column(Text)
    status = Column(String(50), default='open')
    reply = Column(Text)
    created_at = Column(DateTime, default=func.now())

class Setting(Base):
    __tablename__ = 'settings'
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True)
    value = Column(Text)

# ==========================================
# تهيئة قاعدة البيانات
# ==========================================
def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    defaults = [
        ('bot_enabled', 'true'),
        ('show_sender', 'true'),
        ('welcome_message', 'مرحباً بك في بوت مدرسة البتول الطاهرة (ع) القرآنية')
    ]
    for key, value in defaults:
        if not db.query(Setting).filter(Setting.key == key).first():
            db.add(Setting(key=key, value=value))
    db.commit()
    db.close()

# ==========================================
# الدوال المساعدة
# ==========================================
def is_owner(user_id):
    return user_id == OWNER_ID

def is_admin(user_id):
    db = get_db()
    user = db.query(User).filter(User.telegram_id == user_id).first()
    db.close()
    return user and user.role in ['admin', 'owner']

def get_setting(key, default=None):
    db = get_db()
    setting = db.query(Setting).filter(Setting.key == key).first()
    value = setting.value if setting else default
    db.close()
    return value

def generate_ticket_number():
    return ''.join(random.choices(string.digits, k=6))

# ==========================================
# لوحات المفاتيح
# ==========================================
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 إرسال شكوى", callback_data='send_complaint')],
        [InlineKeyboardButton("💡 إرسال اقتراح", callback_data='send_suggestion')],
        [InlineKeyboardButton("🏫 معلومات المدرسة", callback_data='school_info')]
    ])

def complaint_categories_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("شكوى على طالب", callback_data='complaint_student')],
        [InlineKeyboardButton("شكوى إدارية", callback_data='complaint_admin')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='back_to_main')]
    ])

def ticket_status_keyboard(ticket_number):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟢 مفتوحة", callback_data=f'status_open_{ticket_number}'),
            InlineKeyboardButton("🟡 قيد المراجعة", callback_data=f'status_progress_{ticket_number}')
        ],
        [InlineKeyboardButton("🔴 مغلقة", callback_data=f'status_closed_{ticket_number}')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='back_to_main')]
    ])

def admin_panel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 إدارة المشرفين", callback_data='manage_admins')],
        [InlineKeyboardButton("⚙️ إعدادات البوت", callback_data='bot_settings')],
        [InlineKeyboardButton("📊 الإحصائيات", callback_data='statistics')]
    ])

def back_keyboard(callback_data='back_to_main'):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=callback_data)]])

# ==========================================
# الديكوراتور للصلاحيات
# ==========================================
def admin_only_command(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not (is_owner(update.effective_user.id) or is_admin(update.effective_user.id)):
            await update.message.reply_text("❌ ممنوع")
            return
        return await func(update, context)
    return wrapper

def check_banned(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        db = get_db()
        user = db.query(User).filter(User.telegram_id == update.effective_user.id).first()
        db.close()
        if user and user.is_banned:
            await update.message.reply_text("❌ محظور")
            return
        return await func(update, context)
    return wrapper

# ==========================================
# معالجات المستخدمين
# ==========================================
COMPLAINT_CATEGORY, TICKET_CONTENT, SUGGESTION_CONTENT = range(3)

@check_banned
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = get_db()
    db_user = db.query(User).filter(User.telegram_id == user.id).first()
    if not db_user:
        db_user = User(telegram_id=user.id, name=user.full_name, username=user.username)
        db.add(db_user)
    db.commit()
    db.close()
    welcome_text = get_setting('welcome_message', 'مرحباً بك')
    await update.message.reply_text(welcome_text, reply_markup=main_menu_keyboard())

async def send_complaint_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📝 إرسال شكوى\nاختر التصنيف:", reply_markup=complaint_categories_keyboard())
    return COMPLAINT_CATEGORY

async def complaint_category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.replace('complaint_', '')
    context.user_data['ticket_category'] = category
    context.user_data['ticket_type'] = 'complaint'
    await query.edit_message_text("✍️ اكتب نص الشكوى:")
    return TICKET_CONTENT

async def send_suggestion_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['ticket_type'] = 'suggestion'
    await query.edit_message_text("💡 إرسال اقتراح\nاكتب الاقتراح:")
    return SUGGESTION_CONTENT

async def ticket_content_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    content = update.message.text
    
    db = get_db()
    user = db.query(User).filter(User.telegram_id == user_id).first()
    if not user:
        db.close()
        return ConversationHandler.END
    
    ticket_number = generate_ticket_number()
    while db.query(Ticket).filter(Ticket.ticket_number == ticket_number).first():
        ticket_number = generate_ticket_number()
    
    ticket = Ticket(
        ticket_number=ticket_number,
        user_id=user.id,
        type=context.user_data.get('ticket_type', 'complaint'),
        category=context.user_data.get('ticket_category'),
        content=content,
        status='open'
    )
    db.add(ticket)
    db.commit()
    db.close()
    
    # إرسال للمشرفين
    db = get_db()
    admins = db.query(User).filter(User.role.in_(['admin', 'owner', 'moderator'])).all()
    for admin in admins:
        try:
            await context.bot.send_message(admin.telegram_id, f"📬 تذكرة جديدة\nرقم: {ticket_number}\nنص: {content}")
        except:
            pass
    db.close()
    
    await update.message.reply_text(f"✅ تم الاستلام\nرقم التذكرة: {ticket_number}")
    context.user_data.clear()
    return ConversationHandler.END

async def suggestion_content_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await ticket_content_handler(update, context)

async def school_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🏫 مدرسة البتول الطاهرة (ع) القرآنية", reply_markup=back_keyboard())

async def back_to_main_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("القائمة الرئيسية", reply_markup=main_menu_keyboard())

# ==========================================
# معالجات الإدارة
# ==========================================
@admin_only_command
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔧 لوحة التحكم", reply_markup=admin_panel_keyboard())

async def manage_admins_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("👥 إدارة المشرفين", reply_markup=back_keyboard())

async def statistics_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = get_db()
    total_users = db.query(User).count()
    total_tickets = db.query(Ticket).count()
    db.close()
    text = f"📊 الإحصائيات\nالمستخدمين: {total_users}\nالتذاكر: {total_tickets}"
    await query.edit_message_text(text, reply_markup=back_keyboard())

async def back_to_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔧 لوحة التحكم", reply_markup=admin_panel_keyboard())

async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم الإلغاء", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# ==========================================
# معالج الأزرار العام
# ==========================================
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    if data == 'send_complaint':
        return await send_complaint_callback(update, context)
    elif data == 'send_suggestion':
        return await send_suggestion_callback(update, context)
    elif data.startswith('complaint_'):
        return await complaint_category_callback(update, context)
    elif data == 'school_info':
        return await school_info_callback(update, context)
    elif data == 'back_to_main':
        return await back_to_main_callback(update, context)
    elif data == 'manage_admins':
        return await manage_admins_callback(update, context)
    elif data == 'statistics':
        return await statistics_callback(update, context)
    elif data == 'back_to_admin':
        return await back_to_admin_callback(update, context)

# ==========================================
# نقطة البداية
# ==========================================
def main():
    init_db()
    logger.info("بدء تشغيل البوت...")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    user_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(send_complaint_callback, pattern='^send_complaint$'),
            CallbackQueryHandler(send_suggestion_callback, pattern='^send_suggestion$')
        ],
        states={
            COMPLAINT_CATEGORY: [CallbackQueryHandler(complaint_category_callback, pattern='^complaint_')],
            TICKET_CONTENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ticket_content_handler)],
            SUGGESTION_CONTENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, suggestion_content_handler)]
        },
        fallbacks=[CommandHandler('cancel', cancel_handler)]
    )
    
    app.add_handler(CommandHandler('start', start_command))
    app.add_handler(CommandHandler('admin', admin_panel))
    app.add_handler(user_conv)
    app.add_handler(CallbackQueryHandler(callback_router))
    
    print("✅ البوت يعمل الآن...")
    app.run_polling()

if __name__ == '__main__':
    main()
