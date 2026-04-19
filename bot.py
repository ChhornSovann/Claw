# bot.py
"""
Main bot module for Claw Bot
Implements handlers, API integrations, and bot logic
"""

import os
import sys
import json
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, List

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
                
            except Exception as e:
                self.logger.error(f"News API error: {e}")
                return [{'error': 'Failed to fetch news'}]


# ============ CONVERSATION STATES ============

NAME, AGE, FEEDBACK = range(3)
WEATHER_CITY = 3
SURVEY_STATES = [NAME, AGE, FEEDBACK]

# ============ COMMAND HANDLERS ============

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced start command with database logging"""
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
    
    welcome_message = (
        f"👋 Hello {user.first_name}!\n\n"
        f"Welcome to *Claw Bot Pro* 🤖\n\n"
        f"🆕 *Features:*\n"
        f"• /weather - Real-time weather\n"
        f"• /news - Latest headlines\n"
        f"• /stats - Your statistics\n"
        f"• /survey - Interactive survey\n"
        f"• /admin - Bot stats (admin only)\n"
        f"• /help - All commands\n\n"
        f"Your activity is stored securely."
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all available commands"""
    help_text = (
        "📋 *Available Commands:*\n\n"
        "*Basic:*\n"
        "/start - Welcome message\n"
        "/help - This help message\n"
        "/stats - Your usage statistics\n\n"
        "*Features:*\n"
        "/weather - Get weather forecast\n"
        "/news - Latest news headlines\n"
        "/survey - Start interactive survey\n\n"
        "*Admin:*\n"
        "/admin - Bot statistics (admin only)\n\n"
        "💡 Tip: Use inline buttons for quick actions!"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user statistics from database"""
    user = update.effective_user
    db: Database = context.bot_data['db']
    
    stats = await db.get_user_stats(user.id)
    
    if not stats:
        await update.message.reply_text("No data found. Start using the bot!")
        return
    
    commands_text = "\n".join([
        f"  {cmd}: {count}" 
        for cmd, count in stats.get('commands_used', {}).items()
    ]) or "  No commands yet"
    
    stats_text = (
        f"📊 *Your Statistics*\n\n"
        f"👤 User ID: `{user.id}`\n"
        f"💬 Messages: {stats.get('message_count', 0)}\n"
        f"⌨️ Commands: {stats.get('total_commands', 0)}\n\n"
        f"*Command Breakdown:*\n"
        f"{commands_text}\n\n"
        f"📅 Member since: {stats.get('created_at', 'Unknown')[:10]}\n"
        f"🕐 Last active: {stats.get('last_activity', 'Unknown')[:16]}"
    )
    await update.message.reply_text(stats_text, parse_mode='Markdown')


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics (admin only - simple check by user ID)"""
    user = update.effective_user
    db: Database = context.bot_data['db']
    
    # Simple admin check - in production, use a proper admin list
    # For now, allow any user to see stats (or check specific IDs)
    stats = await db.get_bot_stats()
    
    popular = "\n".join([
        f"  {cmd['command']}: {cmd['count']}" 
        for cmd in stats.get('popular_commands', [])
    ]) or "  No data"
    
    admin_text = (
        f"🔐 *Bot Statistics*\n\n"
        f"👥 Total users: {stats.get('total_users', 0)}\n"
        f"📊 Active (7d): {stats.get('active_users_7d', 0)}\n"
        f"⌨️ Total commands: {stats.get('total_commands', 0)}\n\n"
        f"*Top Commands:*\n{popular}"
    )
    await update.message.reply_text(admin_text, parse_mode='Markdown')


# ============ WEATHER HANDLERS ============

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start weather conversation"""
    await update.message.reply_text(
        "🌤 *Weather Forecast*\n\n"
        "Which city would you like to check?\n"
        "(e.g., London, New York, Tokyo)",
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
    
    if not weather_api:
        await update.message.reply_text("❌ Weather service not configured.")
        return ConversationHandler.END
    
    # Show typing indicator
    await update.message.chat.send_action(action='typing')
    
    try:
        weather = await weather_api.get_weather(city)
        
        if 'error' in weather:
            await update.message.reply_text(f"❌ {weather['error']}")
            return ConversationHandler.END
        
        weather_text = (
            f"🌍 *{weather['city']}, {weather['country']}*\n\n"
            f"🌡 Temperature: `{weather['temp']}°C` (feels like {weather['feels_like']}°C)\n"
            f"☁️ Conditions: _{weather['description'].capitalize()}_\n"
            f"💧 Humidity: {weather['humidity']}%\n"
            f"🌬 Wind: {weather['wind_speed']} m/s\n\n"
            f"🕐 Updated: {weather['updated_at'][:16]}"
        )
        
        # Add inline keyboard
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_weather:{city}")],
            [InlineKeyboardButton("📍 Another City", callback_data="new_weather")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            weather_text, 
            parse_mode='Markdown', 
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logging.error(f"Weather error: {e}")
        await update.message.reply_text("❌ Failed to fetch weather. Please try again.")
    
    return ConversationHandler.END


# ============ NEWS HANDLERS ============

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show news categories"""
    keyboard = [
        [InlineKeyboardButton("🌍 General", callback_data="news:general"),
         InlineKeyboardButton("💼 Business", callback_data="news:business")],
        [InlineKeyboardButton("🔬 Technology", callback_data="news:technology"),
         InlineKeyboardButton("🏃 Sports", callback_data="news:sports")],
        [InlineKeyboardButton("🎬 Entertainment", callback_data="news:entertainment"),
         InlineKeyboardButton("🔬 Science", callback_data="news:science")],
        [InlineKeyboardButton("🏥 Health", callback_data="news:health")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📰 *Select News Category:*", 
        parse_mode='Markdown',
        reply_markup=reply_markup
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
    
    if not news_api:
        await query.edit_message_text("❌ News service not configured.")
        return
    
    await query.edit_message_text("📡 Fetching latest news...")
    
    try:
        articles = await news_api.get_news(category=category, page_size=5)
        
        if not articles or 'error' in articles[0]:
            await query.edit_message_text("❌ Failed to fetch news. Try again later.")
            return
        
        news_text = f"📰 *Top {category.capitalize()} Headlines*\n\n"
        for i, article in enumerate(articles[:3], 1):
            title = article['title'] or "No title"
            source = article['source'] or "Unknown"
            date = article['published_at'][:10] if article['published_at'] else "Unknown"
            url = article['url'] or "#"
            
            news_text += (
                f"{i}. *{title}*\n"
                f"🏢 {source} | 📅 {date}\n"
                f"🔗 [Read more]({url})\n\n"
            )
        
        # Add refresh button
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"news:{category}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            news_text, 
            parse_mode='Markdown', 
            reply_markup=reply_markup, 
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logging.error(f"News callback error: {e}")
        await query.edit_message_text("❌ Error fetching news.")


async def refresh_weather_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle weather refresh button"""
    query = update.callback_query
    await query.answer()
    
    city = query.data.split(':')[1]
    weather_api: WeatherAPI = context.bot_data.get('weather_api')
    
    if not weather_api:
        await query.edit_message_text("❌ Weather service not configured.")
        return
    
    await query.edit_message_text("🔄 Refreshing weather data...")
    
    try:
        weather = await weather_api.get_weather(city)
        
        if 'error' in weather:
            await query.edit_message_text(f"❌ {weather['error']}")
            return
        
        weather_text = (
            f"🌍 *{weather['city']}, {weather['country']}*\n\n"
            f"🌡 Temperature: `{weather['temp']}°C` (feels like {weather['feels_like']}°C)\n"
            f"☁️ Conditions: _{weather['description'].capitalize()}_\n"
            f"💧 Humidity: {weather['humidity']}%\n"
            f"🌬 Wind: {weather['wind_speed']} m/s\n\n"
            f"🕐 Updated: {weather['updated_at'][:16]}"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_weather:{city}")],
            [InlineKeyboardButton("📍 Another City", callback_data="new_weather")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            weather_text, 
            parse_mode='Markdown', 
            reply_markup=reply_markup
        )
    except Exception as e:
        logging.error(f"Weather refresh error: {e}")
        await query.edit_message_text("❌ Failed to refresh weather.")


async def new_weather_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start new weather search from button"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🌤 Enter city name:")
    return WEATHER_CITY


# ============ SURVEY CONVERSATION ============

async def survey_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the survey conversation"""
    await update.message.reply_text(
        "📝 *Let's start a quick survey!*\n\n"
        "What's your name? (or /cancel to stop)",
        parse_mode='Markdown'
    )
    return NAME


async def survey_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store name and ask for age"""
    context.user_data['survey_name'] = update.message.text
    await update.message.reply_text(
        f"Nice to meet you, {update.message.text}! 👋\n"
        f"How old are you? (or /cancel to stop)"
    )
    return AGE


async def survey_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store age and ask for feedback"""
    try:
        age = int(update.message.text)
        context.user_data['survey_age'] = age
        await update.message.reply_text(
            "Great! ✨\n"
            "Any feedback about this bot? (or /cancel to stop)"
        )
        return FEEDBACK
    except ValueError:
        await update.message.reply_text(
            "Please enter a valid number for your age."
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
        'feedback': update.message.text
    }
    
    await db.save_conversation_state(user.id, 'survey_completed', survey_data)
    await db.log_command(user.id, 'survey', 'completed')
    
    summary = (
        "✅ *Survey Complete!*\n\n"
        f"Name: {survey_data['name']}\n"
        f"Age: {survey_data['age']}\n"
        f"Feedback: {survey_data['feedback']}\n\n"
        "Thank you for your input! 🎉"
    )
    await update.message.reply_text(summary, parse_mode='Markdown')
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel any ongoing conversation"""
    await update.message.reply_text(
        "❌ Operation cancelled. Send /start to begin again."
    )
    return ConversationHandler.END


# ============ MESSAGE HANDLERS ============

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular text messages"""
    text = update.message.text.lower()
    db: Database = context.bot_data['db']
    
    # Log the message/interaction
    await db.upsert_user(
        user_id=update.effective_user.id,
        username=update.effective_user.username or '',
        first_name=update.effective_user.first_name or '',
        last_name=update.effective_user.last_name or '',
        language_code=update.effective_user.language_code or 'en'
    )
    
    # Simple keyword responses
    if any(word in text for word in ['hello', 'hi', 'hey']):
        await update.message.reply_text(
            f"Hey there! 👋 How can I help you today?\nTry /help for commands."
        )
    elif any(word in text for word in ['bye', 'goodbye', 'see you']):
        await update.message.reply_text(
            "Goodbye! Have a great day! 👋"
        )
    elif 'thank' in text:
        await update.message.reply_text(
            "You're very welcome! 😊"
        )
    else:
        responses = [
            "Interesting! Tell me more 🤔",
            "I see! Is there anything specific you'd like me to help with?",
            "Got it! You can use /help to see what I can do.",
            "Hmm, try /weather or /news for useful info!"
        ]
        import random
        await update.message.reply_text(random.choice(responses))


async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle sticker messages"""
    await update.message.reply_text("Nice sticker! 😎")


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
            "⚠️ An error occurred. Our team has been notified!"
        )


# ============ INITIALIZATION ============

async def post_init(application: Application):
    """Initialize database on startup"""
    db: Database = application.bot_data['db']
    await db.init_db()
    
    # Clear expired cache entries
    cleared = await db.clear_expired_cache()
    logging.info(f"Cleared {cleared} expired cache entries")
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
    
    # Callback handlers
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