from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from config import ADMIN_IDS
from keyboards.inline_kb import get_admin_keyboard, get_back_keyboard
from states.bot_states import OMRStates
import database.db_helper as db

admin_router = Router()

def is_admin_filter(msg_or_call):
    user_id = msg_or_call.from_user.id
    return user_id in ADMIN_IDS

@admin_router.callback_query(F.data == "admin_panel")
async def process_admin_panel(call: CallbackQuery):
    if not is_admin_filter(call):
        await call.answer("Access Denied: Admin role required.", show_alert=True)
        return
    await call.message.edit_text(
        "⚙️ *TEMPLATIZE EXAM ARCHIVES (ADMIN PANEL)*\n\n"
        "Here you can manage OMR answer sheets key definitions.",
        parse_mode="Markdown",
        reply_markup=get_admin_keyboard()
    )

@admin_router.callback_query(F.data == "admin_set_keys")
async def setup_exam_keys(call: CallbackQuery, state: FSMContext):
    if not is_admin_filter(call):
        return
    await state.set_state(OMRStates.waiting_for_admin_keys)
    await call.message.edit_text(
        "🔑 *Define New Answer Key*\n\n"
        "Format required:\n"
        "`EXAM_ID A,B,C,D,E...`\n\n"
        "Example:\n"
        "`MATH101 A,B,D,C,E,A,A,D,E,C,B,A,E,D,C,A,B,B,C,E,E,D,C,B,A,A,B,C,D,E,A,B,C,D,E` (for 35 questions)\n\n"
        "📝 Send the code with keys separated by commas:",
        parse_mode="Markdown",
        reply_markup=get_back_keyboard()
    )

@admin_router.message(OMRStates.waiting_for_admin_keys)
async def handle_key_config_text(msg: Message, state: FSMContext):
    if not is_admin_filter(msg):
        return
        
    parts = msg.text.split(maxsplit=1)
    if len(parts) != 2:
        await msg.reply("❌ Invalid format. Please use: `EXAM_ID A,B,C...`", parse_mode="Markdown")
        return
        
    exam_id, raw_keys = parts[0].upper(), parts[1].upper()
    keys_list = [k.strip() for k in raw_keys.split(",")]
    
    # Validation loop
    valid_options = {"A", "B", "C", "D", "E"}
    for idx, k in enumerate(keys_list):
        if k not in valid_options:
            await msg.reply(f"❌ Error on key #{idx+1}: '{k}' is invalid (Use A, B, C, D, or E).")
            return
            
    # Serialize to standard form
    keys_dict = {str(i+1): items for i, items in enumerate(keys_list)}
    serialized_str = ",".join([f"{k}:{v}" for k,v in keys_dict.items()])
    
    db.save_answer_key(exam_id, serialized_str, msg.from_user.id)
    await state.clear()
    
    await msg.reply(
        f"✅ *Exam Key Registered!*\n\n"
        f"• **Exam ID**: `{exam_id}`\n"
        f"• **Questions quantity**: {len(keys_list)}/35 questions setup.\n\n"
        f"Ready to scan student sheets for this Exam!",
        parse_mode="Markdown",
        reply_markup=get_back_keyboard()
    )

@admin_router.callback_query(F.data == "admin_list_exams")
async def list_exams_database(call: CallbackQuery):
    if not is_admin_filter(call): return
    
    exams = db.get_all_exams()
    if not exams:
        await call.message.edit_text("ℹ️ No active exam templates registered yet. Use 'Set New Answer Key'.", reply_markup=get_back_keyboard())
        return
        
    text = "📜 *REGISTERED EXAM MODELS:*\n\n"
    for row in exams:
        text += f"• **{row[0]}** (Registered: {row[1]})\n"
        
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=get_back_keyboard())
