"""
Internationalization (i18n) utilities for FAB.

Provides translation functionality with support for English (default) and Russian languages.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


class I18n:
    """Internationalization manager for FAB."""
    
    def __init__(self):
        """Initialize I18n with default settings."""
        self.default_language = "en"
        self.supported_languages = ["en", "ru"]
        self.translations: Dict[str, Dict[str, Any]] = {}
        self.current_language = self.default_language
        self._load_translations()
    
    def _load_translations(self) -> None:
        """Load translation files from locales directory."""
        try:
            # Get locales directory path
            current_dir = Path(__file__).parent.parent.parent
            locales_dir = current_dir / "locales"
            
            if not locales_dir.exists():
                logger.warning(f"Locales directory not found: {locales_dir}")
                return
            
            # Load each supported language
            for lang in self.supported_languages:
                lang_file = locales_dir / f"{lang}.json"
                if lang_file.exists():
                    try:
                        with open(lang_file, 'r', encoding='utf-8') as f:
                            self.translations[lang] = json.load(f)
                        logger.info(f"Loaded translations for language: {lang}")
                    except Exception as e:
                        logger.error(f"Failed to load translations for {lang}: {e}")
                else:
                    logger.warning(f"Translation file not found: {lang_file}")
            
            # Ensure default language is available
            if self.default_language not in self.translations:
                logger.error(f"Default language '{self.default_language}' not found!")
                self.translations[self.default_language] = {}
                
        except Exception as e:
            logger.error(f"Failed to load translations: {e}")
            # Initialize empty translations to prevent crashes
            for lang in self.supported_languages:
                self.translations[lang] = {}
    
    def set_language(self, language: str) -> None:
        """Set current language."""
        if language in self.supported_languages:
            self.current_language = language
            logger.debug(f"Language set to: {language}")
        else:
            logger.warning(f"Unsupported language '{language}', using default: {self.default_language}")
            self.current_language = self.default_language
    
    def get_language(self) -> str:
        """Get current language."""
        return self.current_language
    
    def detect_language_from_code(self, language_code: str | None) -> str:
        """Detect language from Telegram language code."""
        if not language_code:
            return self.default_language
        
        # Extract language part (e.g., 'en' from 'en-US')
        lang = language_code.split('-')[0].lower()
        
        if lang == "ru":
            return "ru"
        else:
            return "en"  # Default to English for all other languages
    
    def detect_language_from_header(self, accept_language: str | None) -> str:
        """Detect language from Accept-Language header."""
        if not accept_language:
            return self.default_language
        
        # Parse Accept-Language header (simplified)
        # Format: "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
        languages = []
        for lang_part in accept_language.split(','):
            lang = lang_part.split(';')[0].strip()
            if lang:
                # Extract language code (e.g., 'ru' from 'ru-RU')
                lang_code = lang.split('-')[0].lower()
                if lang_code in self.supported_languages:
                    languages.append(lang_code)
        
        # Return first supported language or default
        return languages[0] if languages else self.default_language
    
    def get_text(self, key: str, language: str | None = None, **kwargs) -> str:
        """
        Get translated text by key.
        
        Args:
            key: Translation key (e.g., 'bot.welcome')
            language: Language code (uses current if None)
            **kwargs: Variables for string formatting
        
        Returns:
            Translated and formatted text
        """
        if language is None:
            language = self.current_language
        
        # Get translation from specified language or fall back to default
        translation = self._get_nested_value(
            self.translations.get(language, {}), key
        )
        
        if translation is None and language != self.default_language:
            # Fall back to default language
            translation = self._get_nested_value(
                self.translations.get(self.default_language, {}), key
            )
            logger.debug(f"Using fallback translation for key: {key}")
        
        if translation is None:
            # Return key if translation not found
            logger.warning(f"Translation not found for key: {key}")
            return key
        
        # Format string with provided variables
        try:
            return translation.format(**kwargs)
        except (KeyError, ValueError) as e:
            logger.warning(f"Failed to format translation '{key}': {e}")
            return translation
    
    def _get_nested_value(self, data: Dict[str, Any], key: str) -> Any:
        """Get value from nested dictionary using dot notation."""
        keys = key.split('.')
        value = data
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return None
    
    def format_duration(self, hours: int, language: str | None = None) -> str:
        """Format duration with proper grammar for the language."""
        if language is None:
            language = self.current_language
        
        if language == "ru":
            if hours == 1:
                return f"{hours} час"
            elif hours in [2, 3, 4]:
                return f"{hours} часа"
            else:
                return f"{hours} часов"
        else:  # English
            if hours == 1:
                return f"{hours} hour"
            else:
                return f"{hours} hours"
    
    def format_remaining_time(self, remaining_seconds: int, language: str | None = None) -> str:
        """Format remaining time with proper grammar for the language."""
        if language is None:
            language = self.current_language
            
        if remaining_seconds <= 0:
            return self.get_text("time.expired", language)
        
        hours = remaining_seconds // 3600
        minutes = (remaining_seconds % 3600) // 60
        seconds = remaining_seconds % 60
        
        parts = []
        
        # Format hours
        if hours > 0:
            if language == "ru":
                if hours == 1:
                    parts.append(self.get_text("time.hours.1", language, count=hours))
                elif hours in [2, 3, 4]:
                    parts.append(self.get_text("time.hours.2", language, count=hours))
                else:
                    parts.append(self.get_text("time.hours.5", language, count=hours))
            else:  # English
                if hours == 1:
                    parts.append(self.get_text("time.hours.1", language, count=hours))
                else:
                    parts.append(self.get_text("time.hours.other", language, count=hours))
        
        # Format minutes
        if minutes > 0:
            if language == "ru":
                parts.append(self.get_text("time.minutes.other", language, count=minutes))
            else:  # English
                if minutes == 1:
                    parts.append(self.get_text("time.minutes.1", language, count=minutes))
                else:
                    parts.append(self.get_text("time.minutes.other", language, count=minutes))
        
        # Format seconds (only if no hours/minutes)
        if not parts and seconds > 0:
            if language == "ru":
                parts.append(self.get_text("time.seconds.other", language, count=seconds))
            else:  # English
                if seconds == 1:
                    parts.append(self.get_text("time.seconds.1", language, count=seconds))
                else:
                    parts.append(self.get_text("time.seconds.other", language, count=seconds))
        
        if not parts:
            return self.get_text("time.less_than_second", language)
        
        # Join with " " and add "remaining/осталось" prefix
        remaining_text = self.get_text("time.remaining", language)
        return f"{remaining_text} " + " ".join(parts)


# Global i18n instance
i18n = I18n()

