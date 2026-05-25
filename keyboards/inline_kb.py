from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_main_keyboard(is_admin: bool = False):
    buttons = [
        [InlineKeyboardButton(text="📷 Test varaqasini tekshirish", callback_data="start_scanning")],
        [InlineKeyboardButton(text="📊 Mening natijalarim", callback_data="my_history"),
         InlineKeyboardButton(text="🏆 Reyting", callback_data="view_leaderboard")],
        [InlineKeyboardButton(text="ℹ️ Qo'llanma", callback_data="tutorial_info")]
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="⚙️ Admin panel", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Javob kalitini kiritish", callback_data="admin_set_keys")],
        [InlineKeyboardButton(text="📜 Kalitlar ro'yxati", callback_data="admin_list_exams")],
        [InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="back_to_main")]
    ])


def get_back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Asosiy menyuga qaytish", callback_data="back_to_main")]
    ])


def get_tutorial_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="back_to_main")]
    ])
