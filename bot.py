# bot.py
"""
Main bot module for Claw Bot
Implements handlers, API integrations, and bot logic with modern UI
"""

import os
import sys
import json
import logging
import asyncio
import random
from datetime import datetime
from typing import Dict, Any, List

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonCommands, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

# Import local modules
from config import Config
from database import Database

# ============ API INTEGRATIONS ============

class WeatherAPI:
    """OpenWeatherMap API integration with database caching"""
    
    def __init__(self, api_key: str, db: Database):
        self.api_key = api_key
        self.db = db
        self.base_url = "https://api.openweathermap.org/data/2.5/weather"
        self.logger = logging.getLogger(__name__)
    
    async def get_weather(self, city: str) -> Dict[str, Any]:
        """Get weather with database caching"""
        if not self.api_key:
            return {'error': 'Weather API not configured'}
        
        cache_key = f"weather_{city.lower()}"
        
        # Check cache first (15 minute TTL for weather)
        cached = await self.db.get_cached_response('weather', cache_key)
        if cached:
            self.logger.info(f"Cache hit for weather: {city}")
            return json.loads(cached)
        
        # Fetch from API
        async with httpx.AsyncClient() as client:
            params = {
                'q': city,
                'appid': self.api_key,
                'units': 'metric',
                'lang': 'en'
            }
            try:
                response = await client.get(self.base_url, params=params, timeout=10.0)
                response.raise_for_status()
                data = response.json()
                
                # Format for display
                weather_data = {
                    'city': data['name'],
                    'country': data['sys']['country'],
                    'temp': data['main']['temp'],
                    'feels_like': data['main']['feels_like'],
                    'humidity': data['main']['humidity'],
                    'description': data['weather'][0]['description'],
                    'wind_speed': data['wind']['speed'],
                    'icon': data['weather'][0]['icon'],
                    'updated_at': datetime.now().isoformat()
                }
                
                # Cache for 15 minutes
                await self.db.cache_api_response('weather', cache_key, 
                                                  json.dumps(weather_data), 15)
                return weather_data
                
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    return {'error': f"City '{city}' not found"}
                elif e.response.status_code == 401:
                    return {'error': "Invalid API key. Please check OPENWEATHER_API_KEY."}
                self.logger.error(f"Weather API HTTP error: {e}")
                return {'error': f"API error: {e.response.status_code}"}
            except Exception as e:
                self.logger.error(f"Weather API error: {e}")
                return {'error': "Failed to fetch weather data"}


class NewsAPI:
    """NewsAPI.org integration with database caching"""
    
    def __init__(self, api_key: str, db: Database):
        self.api_key = api_key
        self.db = db
        self.base_url = "https://newsapi.org/v2/top-headlines"
        self.logger = logging.getLogger(__name__)
    
    async def get_news(self, category: str = 'general', country: str = 'us', 
                       page_size: int = 5) -> List[Dict]:
        """Get top news headlines with caching"""
        if not self.api_key:
            return [{'error': 'News API not configured'}]
        
        cache_key = f"news_{category}_{country}_{page_size}"
        
        # Check cache (60 minute TTL for news)
        cached = await self.db.get_cached_response('news', cache_key)
        if cached:
            self.logger.info(f"Cache hit for news: {category}")
            return json.loads(cached)
        
        async with httpx.AsyncClient() as client:
            params = {
                'category': category,
                'country': country,
                'pageSize': page_size,
                'apiKey': self.api_key
            }
            try:
                response = await client.get(self.base_url, params=params, timeout=10.0)
                response.raise_for_status()
                data = response.json()
                
                articles = []
                for article in data.get('articles', []):
                    articles.append({
                        'title': article['title'],
                        'description': article['description'],
                        'url': article['url'],
                        'source': article['source']['name'],
                        'published_at': article['publishedAt']
                    })
                
                # Cache for 60 minutes
                await self.db.cache_api_response('news', cache_key, 
                                                  json.dumps(articles), 60)
                return articles
                
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    return [{'error': 'Invalid API key. Please check NEWS_API_KEY.'}]
                self.logger.error(f"News API HTTP error: {e}")
                return [{'error': f'API error: {e.response.status_code}'}]
            except Exception as e:
                self.logger.error(f"News API error: {e}")
                return [{'error': 'Failed to fetch news'}]


# ============ UI COMPONENTS ============

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Main menu inline keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("🌤 Weather", callback_data="menu:weather"),
            InlineKeyboardButton("📰 News", callback_data="menu:news")
        ],
        [
            InlineKeyboardButton("📊 My Stats", callback_data="menu:stats"),
            InlineKeyboardButton("📝 Survey", callback_data="menu:survey")
        ],
        [
            InlineKeyboardButton("❓ Help", callback_data="menu:help"),
            InlineKeyboardButton("🔧 Admin", callback_data="menu:admin")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_news_categories_keyboard() -> InlineKeyboardMarkup:
    """News category selection keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("🌍 General", callback_data="news:general"),
            InlineKeyboardButton("💼 Business", callback_data="news:business")
        ],
        [
            InlineKeyboardButton("🔬 Technology", callback_data="news:technology"),
            InlineKeyboardButton("🏃 Sports", callback_data="news:sports")
        ],
        [
            InlineKeyboardButton("🎬 Entertainment", callback_data="news:entertainment"),
            InlineKeyboardButton("🔬 Science", callback_data="news:science")
        ],
        [
            InlineKeyboardButton("🏥 Health", callback_data="news:health"),
            InlineKeyboardButton("🔙 Back", callback_data="menu:main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_weather_action_keyboard(city: str) -> InlineKeyboardMarkup:
    """Weather action keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_weather:{city}"),
            InlineKeyboardButton("📍 New City", callback_data="new_weather")
        ],
        [
            InlineKeyboardButton("🔙 Main Menu", callback_data="menu:main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_back_keyboard() -> InlineKeyboardMarkup:
    """Simple back button"""
    keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="menu:main")]]
    return InlineKeyboardMarkup(keyboard)


# ============ CONVERSATION STATES ============

NAME, AGE, FEEDBACK = range(3)
WEATHER_CITY = 3

# ============ COMMAND HANDLERS ============

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced start command with modern UI"""
    user = update.effective_user
    db: Database = context.bot_data['db']
    
    # Store user in database
    await db.upsert_user(
        user_id=user.id,
        username=user.username or '',
        first_name=user.first_name or '',
        last_name=user.last_name or '',
        language_code=user.language_code or 'en'
    )
    
    welcome_text = (
        f"👋 *Welcome, {user.first_name}!*\n\n"
        f"🤖 *Claw Bot Pro* is your personal assistant with:\n"
        f"• Real-time weather updates\n"
        f"• Latest news headlines\n"
        f"• Personal statistics tracking\n"
        f"• Interactive surveys\n\n"
        f"Select an option below or use /help for all commands."
    )
    
    await update.message.reply_text(
        welcome_text, 
        parse_mode='Markdown',
        reply_markup=get_main_menu_keyboard()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Modern help command with categorized commands"""
    help_text = (
        "📚 *Command Guide*\n\n"
        "*🎯 Quick Actions:*\n"
        "• /start - Main menu with buttons\n"
        "• /weather - Check weather anywhere\n"
        "• /news - Latest headlines\n\n"
        "*📊 Personal:*\n"
        "• /stats - Your usage statistics\n"
        "• /survey - Share your feedback\n\n"
        "*🔧 System:*\n"
        "• /help - This help message\n"
        "• /cancel - Cancel current operation\n\n"
        "💡 *Tip:* Use the inline buttons below for quick navigation!"
    )
    
    await update.message.reply_text(
        help_text, 
        parse_mode='Markdown',
        reply_markup=get_main_menu_keyboard()
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user statistics with modern formatting"""
    user = update.effective_user
    db: Database = context.bot_data['db']
    
    stats = await db.get_user_stats(user.id)
    
    if not stats:
        await update.message.reply_text(
            "No data found yet. Start using the bot to see your stats!",
            reply_markup=get_main_menu_keyboard()
        )
        return
    
    # Format commands nicely
    commands_lines = []
    for cmd, count in sorted(stats.get('commands_used', {}).items(), 
                            key=lambda x: x[1], reverse=True)[:5]:
        bar = "█" * min(count, 10) + "░" * (10 - min(count, 10))
        commands_lines.append(f"`{bar}` {cmd}: {count}")
    
    commands_text = "\n".join(commands_lines) if commands_lines else "_No commands yet_"
    
    stats_text = (
        f"📊 *Your Activity Dashboard*\n\n"
        f"👤 *User:* `{user.id}`\n"
        f"💬 *Messages:* `{stats.get('message_count', 0)}`\n"
        f"⌨️ *Commands:* `{stats.get('total_commands', 0)}`\n\n"
        f"*📈 Top Commands:*\n"
        f"{commands_text}\n\n"
        f"📅 *Member since:* `{stats.get('created_at', 'Unknown')[:10]}`\n"
        f"🕐 *Last active:* `{stats.get('last_activity', 'Unknown')[:16]}`"
    )
    
    await update.message.reply_text(
        stats_text, 
        parse_mode='Markdown',
        reply_markup=get_main_menu_keyboard()
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin dashboard with bot statistics"""
    user = update.effective_user
    db: Database = context.bot_data['db']
    
    stats = await db.get_bot_stats()
    
    popular_lines = []
    for cmd in stats.get('popular_commands', [])[:5]:
        pct = (cmd['count'] / max(stats.get('total_commands', 1), 1)) * 100
        bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
        popular_lines.append(f"`{bar}` {cmd['command']}: {cmd['count']}")
    
    popular_text = "\n".join(popular_lines) if popular_lines else "_No data yet_"
    
    admin_text = (
        f"🔐 *Bot Admin Dashboard*\n\n"
        f"👥 *Total Users:* `{stats.get('total_users', 0)}`\n"
        f"📊 *Active (7d):* `{stats.get('active_users_7d', 0)}`\n"
        f"⌨️ *Total Commands:* `{stats.get('total_commands', 0)}`\n\n"
        f"*📊 Command Distribution:*\n"
        f"{popular_text}\n\n"
        f"_Last updated: {datetime.now().strftime('%H:%M:%S')}_"
    )
    
    await update.message.reply_text(
        admin_text, 
        parse_mode='Markdown',
        reply_markup=get_main_menu_keyboard()
    )


# ============ WEATHER HANDLERS ============

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start weather conversation"""
    weather_api: WeatherAPI = context.bot_data.get('weather_api')
    
    if not weather_api or not weather_api.api_key:
        await update.message.reply_text(
            "⚠️ *Weather service not configured*\n\n"
            "Please set OPENWEATHER_API_KEY environment variable.",
            parse_mode='Markdown',
            reply_markup=get_main_menu_keyboard()
        )
        return ConversationHandler.END
    
    await update.message.reply_text(
        "🌤 *Weather Forecast*\n\n"
        "Which city would you like to check?\n"
        "_Examples: London, New York, Tokyo, Paris_",
        parse_mode='Markdown'
    )
    return WEATHER_CITY


async def weather_city_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle city input and fetch weather"""
    city = update.message.text.strip()
    weather_api: WeatherAPI = context.bot_data.get('weather_api')
    db: Database = context.bot_data['db']
    
    # Log command
    await db.log_command(update.effective_user.id, 'weather', city)
    
    # Show typing indicator
    await update.message.chat.send_action(action='typing')
    
    try:
        weather = await weather_api.get_weather(city)
        
        if 'error' in weather:
            error_msg = weather['error']
            if 'API key' in error_msg:
                error_msg += "\n\nPlease contact the administrator."
            
            await update.message.reply_text(
                f"❌ *Error:* {error_msg}",
                parse_mode='Markdown',
                reply_markup=get_main_menu_keyboard()
            )
            return ConversationHandler.END
        
        # Weather icon mapping
        icon_map = {
            '01d': '☀️', '01n': '🌙',
            '02d': '⛅', '02n': '☁️',
            '03d': '☁️', '03n': '☁️',
            '04d': '☁️', '04n': '☁️',
            '09d': '🌧️', '09n': '🌧️',
            '10d': '🌦️', '10n': '🌧️',
            '11d': '⛈️', '11n': '⛈️',
            '13d': '❄️', '13n': '❄️',
            '50d': '🌫️', '50n': '🌫️'
        }
        weather_icon = icon_map.get(weather['icon'], '🌡️')
        
        weather_text = (
            f"{weather_icon} *{weather['city']}, {weather['country']}*\n\n"
            f"🌡 *Temperature:* `{weather['temp']}°C` (feels like {weather['feels_like']}°C)\n"
            f"☁️ *Conditions:* _{weather['description'].capitalize()}_\n"
            f"💧 *Humidity:* `{weather['humidity']}%`\n"
            f"🌬 *Wind:* `{weather['wind_speed']} m/s`\n\n"
            f"🕐 Updated: `{weather['updated_at'][:16]}`"
        )
        
        await update.message.reply_text(
            weather_text, 
            parse_mode='Markdown',
            reply_markup=get_weather_action_keyboard(city)
        )
        
    except Exception as e:
        logging.error(f"Weather error: {e}")
        await update.message.reply_text(
            "❌ Failed to fetch weather. Please try again later.",
            reply_markup=get_main_menu_keyboard()
        )
    
    return ConversationHandler.END


# ============ NEWS HANDLERS ============

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show news categories"""
    news_api: NewsAPI = context.bot_data.get('news_api')
    
    if not news_api or not news_api.api_key:
        await update.message.reply_text(
            "⚠️ *News service not configured*\n\n"
            "Please set NEWS_API_KEY environment variable.",
            parse_mode='Markdown',
            reply_markup=get_main_menu_keyboard()
        )
        return
    
    await update.message.reply_text(
        "📰 *Select News Category:*", 
        parse_mode='Markdown',
        reply_markup=get_news_categories_keyboard()
    )


async def news_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle news category selection"""
    query = update.callback_query
    await query.answer()
    
    category = query.data.split(':')[1]
    news_api: NewsAPI = context.bot_data.get('news_api')
    db: Database = context.bot_data['db']
    
    # Log command
    await db.log_command(update.effective_user.id, 'news', category)
    
    if not news_api or not news_api.api_key:
        await query.edit_message_text(
            "⚠️ News service not configured.",
            reply_markup=get_back_keyboard()
        )
        return
    
    await query.edit_message_text("📡 *Fetching latest news...*", parse_mode='Markdown')
    
    try:
        articles = await news_api.get_news(category=category, page_size=5)
        
        if not articles:
            await query.edit_message_text(
                "❌ No news available.",
                reply_markup=get_back_keyboard()
            )
            return
        
        if 'error' in articles[0]:
            error_msg = articles[0]['error']
            await query.edit_message_text(
                f"❌ {error_msg}",
                reply_markup=get_back_keyboard()
            )
            return
        
        news_text = f"📰 *{category.capitalize()} Headlines*\n\n"
        for i, article in enumerate(articles[:3], 1):
            title = article.get('title') or "No title"
            source = article.get('source') or "Unknown"
            date = article.get('published_at', '')[:10] if article.get('published_at') else "Today"
            url = article.get('url') or "#"
            
            # Truncate long titles
            display_title = title[:60] + "..." if len(title) > 60 else title
            
            news_text += (
                f"{i}. *{display_title}*\n"
                f"🏢 {source} | 📅 {date}\n"
                f"🔗 [Read article]({url})\n\n"
            )
        
        # Add refresh and back buttons
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data=f"news:{category}")],
            [InlineKeyboardButton("🔙 Back to Categories", callback_data="menu:news"),
             InlineKeyboardButton("🏠 Main Menu", callback_data="menu:main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            news_text, 
            parse_mode='Markdown', 
            reply_markup=reply_markup, 
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logging.error(f"News callback error: {e}")
        await query.edit_message_text(
            "❌ Error fetching news. Please try again.",
            reply_markup=get_back_keyboard()
        )


# ============ MENU CALLBACKS ============

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle main menu navigation"""
    query = update.callback_query
    await query.answer()
    
    action = query.data.split(':')[1]
    
    if action == "main":
        # Return to main menu
        user = update.effective_user
        welcome_text = (
            f"👋 *Welcome back, {user.first_name}!*\n\n"
            f"Select an option below:"
        )
        await query.edit_message_text(
            welcome_text,
            parse_mode='Markdown',
            reply_markup=get_main_menu_keyboard()
        )
    
    elif action == "weather":
        # Start weather flow
        weather_api: WeatherAPI = context.bot_data.get('weather_api')
        if not weather_api or not weather_api.api_key:
            await query.edit_message_text(
                "⚠️ *Weather service not configured*\n\n"
                "Please set OPENWEATHER_API_KEY environment variable.",
                parse_mode='Markdown',
                reply_markup=get_back_keyboard()
            )
        else:
            await query.edit_message_text(
                "🌤 *Weather Forecast*\n\n"
                "Which city would you like to check?\n"
                "_Examples: London, New York, Tokyo_",
                parse_mode='Markdown'
            )
            # Set conversation state
            context.user_data['expecting'] = 'weather_city'
    
    elif action == "news":
        await query.edit_message_text(
            "📰 *Select News Category:*",
            parse_mode='Markdown',
            reply_markup=get_news_categories_keyboard()
        )
    
    elif action == "stats":
        # Show stats
        db: Database = context.bot_data['db']
        stats = await db.get_user_stats(update.effective_user.id)
        
        if not stats:
            await query.edit_message_text(
                "No data found yet. Start using the bot!",
                reply_markup=get_main_menu_keyboard()
            )
            return
        
        commands_lines = []
        for cmd, count in sorted(stats.get('commands_used', {}).items(), 
                                key=lambda x: x[1], reverse=True)[:5]:
            bar = "█" * min(count, 10) + "░" * (10 - min(count, 10))
            commands_lines.append(f"`{bar}` {cmd}: {count}")
        
        commands_text = "\n".join(commands_lines) if commands_lines else "_No commands yet_"
        
        stats_text = (
            f"📊 *Your Activity*\n\n"
            f"💬 Messages: `{stats.get('message_count', 0)}`\n"
            f"⌨️ Commands: `{stats.get('total_commands', 0)}`\n\n"
            f"*Top Commands:*\n{commands_text}\n\n"
            f"📅 Member since: `{stats.get('created_at', 'Unknown')[:10]}`"
        )
        await query.edit_message_text(
            stats_text,
            parse_mode='Markdown',
            reply_markup=get_main_menu_keyboard()
        )
    
    elif action == "survey":
        await query.edit_message_text(
            "📝 *Let's start a quick survey!*\n\n"
            "What's your name?\n\n"
            "_Send /cancel to stop_",
            parse_mode='Markdown'
        )
        context.user_data['survey_step'] = 'name'
    
    elif action == "help":
        help_text = (
            "📚 *Quick Help*\n\n"
            "*Available Commands:*\n"
            "• /start - Main menu\n"
            "• /weather - Weather check\n"
            "• /news - News headlines\n"
            "• /stats - Your statistics\n"
            "• /survey - Feedback survey\n"
            "• /admin - Bot statistics\n\n"
            "_Use the buttons below to navigate!_"
        )
        await query.edit_message_text(
            help_text,
            parse_mode='Markdown',
            reply_markup=get_main_menu_keyboard()
        )
    
    elif action == "admin":
        db: Database = context.bot_data['db']
        stats = await db.get_bot_stats()
        
        popular_lines = []
        for cmd in stats.get('popular_commands', [])[:5]:
            pct = (cmd['count'] / max(stats.get('total_commands', 1), 1)) * 100
            bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
            popular_lines.append(f"`{bar}` {cmd['command']}: {cmd['count']}")
        
        popular_text = "\n".join(popular_lines) if popular_lines else "_No data_"
        
        admin_text = (
            f"🔐 *Admin Dashboard*\n\n"
            f"👥 Users: `{stats.get('total_users', 0)}`\n"
            f"📊 Active (7d): `{stats.get('active_users_7d', 0)}`\n"
            f"⌨️ Commands: `{stats.get('total_commands', 0)}`\n\n"
            f"*Top Commands:*\n{popular_text}"
        )
        await query.edit_message_text(
            admin_text,
            parse_mode='Markdown',
            reply_markup=get_main_menu_keyboard()
        )


async def refresh_weather_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle weather refresh button"""
    query = update.callback_query
    await query.answer()
    
    city = query.data.split(':')[1]
    weather_api: WeatherAPI = context.bot_data.get('weather_api')
    
    if not weather_api:
        await query.edit_message_text("❌ Weather service not available.")
        return
    
    await query.edit_message_text("🔄 *Refreshing...*", parse_mode='Markdown')
    
    try:
        weather = await weather_api.get_weather(city)
        
        if 'error' in weather:
            await query.edit_message_text(
                f"❌ {weather['error']}",
                reply_markup=get_back_keyboard()
            )
            return
        
        icon_map = {
            '01d': '☀️', '01n': '🌙', '02d': '⛅', '02n': '☁️',
            '03d': '☁️', '03n': '☁️', '04d': '☁️', '04n': '☁️',
            '09d': '🌧️', '09n': '🌧️', '10d': '🌦️', '10n': '🌧️',
            '11d': '⛈️', '11n': '⛈️', '13d': '❄️', '13n': '❄️',
            '50d': '🌫️', '50n': '🌫️'
        }
        weather_icon = icon_map.get(weather['icon'], '🌡️')
        
        weather_text = (
            f"{weather_icon} *{weather['city']}, {weather['country']}*\n\n"
            f"🌡 *Temperature:* `{weather['temp']}°C` (feels like {weather['feels_like']}°C)\n"
            f"☁️ *Conditions:* _{weather['description'].capitalize()}_\n"
            f"💧 *Humidity:* `{weather['humidity']}%`\n"
            f"🌬 *Wind:* `{weather['wind_speed']} m/s`\n\n"
            f"🕐 Updated: `{weather['updated_at'][:16]}`"
        )
        
        await query.edit_message_text(
            weather_text,
            parse_mode='Markdown',
            reply_markup=get_weather_action_keyboard(city)
        )
    except Exception as e:
        logging.error(f"Weather refresh error: {e}")
        await query.edit_message_text(
            "❌ Failed to refresh.",
            reply_markup=get_back_keyboard()
        )


async def new_weather_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start new weather search from button"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🌤 *Enter city name:*\n\n_Examples: London, Tokyo, New York_",
        parse_mode='Markdown'
    )
    context.user_data['expecting'] = 'weather_city'


# ============ SURVEY CONVERSATION ============

async def survey_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the survey conversation"""
    await update.message.reply_text(
        "📝 *Quick Survey*\n\n"
        "Question 1/3: What's your name?\n\n"
        "_Send /cancel to stop_",
        parse_mode='Markdown'
    )
    return NAME


async def survey_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store name and ask for age"""
    context.user_data['survey_name'] = update.message.text
    await update.message.reply_text(
        f"✅ Got it, *{update.message.text}*!\n\n"
        f"Question 2/3: How old are you?",
        parse_mode='Markdown'
    )
    return AGE


async def survey_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store age and ask for feedback"""
    try:
        age = int(update.message.text)
        if age < 1 or age > 120:
            raise ValueError("Invalid age")
        
        context.user_data['survey_age'] = age
        await update.message.reply_text(
            "✅ Great!\n\n"
            "Question 3/3: Any feedback about this bot?\n"
            "_What features would you like to see?_",
            parse_mode='Markdown'
        )
        return FEEDBACK
    except ValueError:
        await update.message.reply_text(
            "❌ Please enter a valid age (1-120)."
        )
        return AGE


async def survey_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Complete the survey and save to database"""
    user = update.effective_user
    db: Database = context.bot_data['db']
    
    # Save conversation data to database
    survey_data = {
        'name': context.user_data.get('survey_name'),
        'age': context.user_data.get('survey_age'),
        'feedback': update.message.text,
        'completed_at': datetime.now().isoformat()
    }
    
    await db.save_conversation_state(user.id, 'survey_completed', survey_data)
    await db.log_command(user.id, 'survey', 'completed')
    
    summary = (
        "🎉 *Survey Complete!*\n\n"
        f"Thank you for your feedback, *{survey_data['name']}*!\n\n"
        f"📊 Summary:\n"
        f"• Age: {survey_data['age']}\n"
        f"• Feedback: _{survey_data['feedback'][:50]}..._\n\n"
        f"Your input helps us improve! 🚀"
    )
    
    await update.message.reply_text(
        summary, 
        parse_mode='Markdown',
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel any ongoing conversation"""
    await update.message.reply_text(
        "❌ *Operation cancelled.*\n\n"
        "Send /start to return to the main menu.",
        parse_mode='Markdown',
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END


# ============ MESSAGE HANDLERS ============

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular text messages - NO API calls here"""
    text = update.message.text
    text_lower = text.lower()
    db: Database = context.bot_data['db']
    
    # Log the interaction (database only, no external APIs)
    await db.upsert_user(
        user_id=update.effective_user.id,
        username=update.effective_user.username or '',
        first_name=update.effective_user.first_name or '',
        last_name=update.effective_user.last_name or '',
        language_code=update.effective_user.language_code or 'en'
    )
    
    # Check if we're expecting specific input
    if context.user_data.get('expecting') == 'weather_city':
        # Handle weather city input inline
        context.user_data['expecting'] = None
        # Simulate the weather conversation handler
        update.message.text = text  # Ensure text is set
        return await weather_city_handler(update, context)
    
    if context.user_data.get('survey_step') == 'name':
        context.user_data['survey_step'] = 'age'
        context.user_data['survey_name'] = text
        await update.message.reply_text(
            f"✅ Got it, *{text}*!\n\nQuestion 2/3: How old are you?",
            parse_mode='Markdown'
        )
        return
    
    # Simple keyword responses
    greetings = ['hello', 'hi', 'hey', 'hola', 'bonjour', 'ciao']
    goodbyes = ['bye', 'goodbye', 'see you', 'cya', 'farewell']
    thanks = ['thanks', 'thank you', 'thx', 'ty', 'gracias', 'merci']
    
    if any(word in text_lower for word in greetings):
        await update.message.reply_text(
            f"👋 Hey *{update.effective_user.first_name}*! Welcome back!\n\n"
            f"Use the menu below or type /help for commands.",
            parse_mode='Markdown',
            reply_markup=get_main_menu_keyboard()
        )
    elif any(word in text_lower for word in goodbyes):
        await update.message.reply_text(
            "👋 Goodbye! Have a great day!\n\n"
            "Come back anytime with /start",
            reply_markup=get_main_menu_keyboard()
        )
    elif any(word in text_lower for word in thanks):
        await update.message.reply_text(
            "😊 You're very welcome!\n\n"
            "Need anything else? Use the menu below!",
            reply_markup=get_main_menu_keyboard()
        )
    else:
        # Smart fallback with suggestions
        responses = [
            "🤔 I see! Need help? Try these:",
            "💡 Not sure what you mean. How about:",
            "🎯 I can help you with:"
        ]
        
        await update.message.reply_text(
            f"{random.choice(responses)}\n\n"
            f"• /weather - Check weather\n"
            f"• /news - Read news\n"
            f"• /stats - Your activity\n"
            f"• /survey - Give feedback",
            reply_markup=get_main_menu_keyboard()
        )


async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle sticker messages"""
    await update.message.reply_text(
        "😎 Nice sticker!\n\n"
        "What can I do for you?",
        reply_markup=get_main_menu_keyboard()
    )


# ============ ERROR HANDLING ============

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors to database and notify user"""
    logging.error(f"Update {update} caused error {context.error}")
    
    db: Database = context.bot_data.get('db')
    if db and update and update.effective_user:
        await db.log_command(
            update.effective_user.id,
            'error',
            str(context.error)[:100],
            success=False,
            error_message=str(context.error)[:200]
        )
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ *Oops! Something went wrong.*\n\n"
            "Our team has been notified. Please try again later or use /start.",
            parse_mode='Markdown',
            reply_markup=get_main_menu_keyboard()
        )


# ============ INITIALIZATION ============

async def post_init(application: Application):
    """Initialize database and bot commands menu on startup"""
    db: Database = application.bot_data['db']
    await db.init_db()
    
    # Clear expired cache entries
    cleared = await db.clear_expired_cache()
    logging.info(f"Cleared {cleared} expired cache entries")
    
    # Set up command menu (shows in Telegram UI)
    commands = [
        BotCommand("start", "🏠 Main menu"),
        BotCommand("weather", "🌤 Check weather"),
        BotCommand("news", "📰 Latest news"),
        BotCommand("stats", "📊 Your statistics"),
        BotCommand("survey", "📝 Feedback survey"),
        BotCommand("help", "❓ Help & commands"),
        BotCommand("cancel", "❌ Cancel operation")
    ]
    
    await application.bot.set_my_commands(commands)
    logging.info("Bot commands menu set up")
    logging.info("Bot initialized successfully")


def main():
    """Main entry point"""
    # Setup logging
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    # Load configuration
    config = Config()
    config.validate()
    
    # Initialize database
    db = Database(config.DATABASE_PATH)
    
    # Initialize APIs (optional)
    weather_api = WeatherAPI(config.OPENWEATHER_API_KEY, db) if config.OPENWEATHER_API_KEY else None
    news_api = NewsAPI(config.NEWS_API_KEY, db) if config.NEWS_API_KEY else None
    
    # Build application
    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .concurrent_updates(True)
        .build()
    )
    
    # Store in bot_data for access in handlers
    application.bot_data['db'] = db
    application.bot_data['weather_api'] = weather_api
    application.bot_data['news_api'] = news_api
    application.bot_data['config'] = config
    
    # ============ ADD HANDLERS ============
    
    # Basic commands
    application.add_handler(CommandHandler('start', start_command))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('stats', stats_command))
    application.add_handler(CommandHandler('admin', admin_command))
    application.add_handler(CommandHandler('cancel', cancel_command))
    
    # Weather conversation
    weather_conv = ConversationHandler(
        entry_points=[CommandHandler('weather', weather_command)],
        states={
            WEATHER_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, weather_city_handler)]
        },
        fallbacks=[CommandHandler('cancel', cancel_command)],
    )
    application.add_handler(weather_conv)
    
    # Survey conversation
    survey_conv = ConversationHandler(
        entry_points=[CommandHandler('survey', survey_start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, survey_name)],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, survey_age)],
            FEEDBACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, survey_feedback)],
        },
        fallbacks=[CommandHandler('cancel', cancel_command)],
    )
    application.add_handler(survey_conv)
    
    # Callback handlers - menu navigation
    application.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu:"))
    application.add_handler(CallbackQueryHandler(news_callback, pattern="^news:"))
    application.add_handler(CallbackQueryHandler(refresh_weather_callback, pattern="^refresh_weather:"))
    application.add_handler(CallbackQueryHandler(new_weather_callback, pattern="^new_weather$"))
    
    # Message handlers (must be last)
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    # ============ RUN BOT ============
    
    if config.is_webhook_mode:
        logging.info(f"Starting webhook on port {config.PORT}")
        application.run_webhook(
            listen="0.0.0.0",
            port=config.PORT,
            webhook_url=config.WEBHOOK_URL,
            secret_token=config.WEBHOOK_SECRET if config.WEBHOOK_SECRET else None
        )
    else:
        logging.info("Starting polling mode (development)")
        application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()