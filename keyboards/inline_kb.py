from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_main_keyboard(is_admin: bool = False):
    """Provides a primary menu dashboard mapping."""
    buttons = [
        [InlineKeyboardButton(text="📤 Upload OMR Sheet", callback_data="start_scanning")],
        [InlineKeyboardButton(text="📊 My History", callback_data="my_history"),
         InlineKeyboardButton(text="🏆 Leaderboard", callback_data="view_leaderboard")],
        [InlineKeyboardButton(text="ℹ️ How it Works & Tutorial", callback_data="tutorial_info")]
    ]
    
    if is_admin:
        buttons.append([InlineKeyboardButton(text="⚙️ Admin panel (Keys DB)", callback_data="admin_panel")])
        
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_keyboard():
    buttons = [
        [InlineKeyboardButton(text="🔑 Set New Answer Key", callback_data="admin_set_keys")],
        [InlineKeyboardButton(text="📜 List Existing Exams", callback_data="admin_list_exams")],
        [InlineKeyboardButton(text="📥 Export Results (.CSV)", callback_data="admin_export_results")],
        [InlineKeyboardButton(text="🔙 Back to User Menu", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_back_keyboard():
    buttons = [
        [InlineKeyboardButton(text="🔙 Back to Main Menu", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_tutorial_keyboard():
    buttons = [
        [InlineKeyboardButton(text="📚 Get Blank 35-Q Form", callback_data="get_blank_sheet")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
