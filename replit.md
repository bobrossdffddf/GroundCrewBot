# Overview

This is a Discord bot application built with discord.py that provides shift tracking and operation attendance management for gaming communities or organizations. The bot uses slash commands for user interaction and maintains persistent data storage through JSON files. Key features include operation scheduling with attendance tracking, shift management, and automated reminders.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Bot Framework
- **Discord.py Library**: Uses the discord.py library with the commands extension for bot functionality
- **Slash Commands**: Implements modern Discord slash commands through app_commands for better user experience
- **Intent Management**: Uses minimal Discord intents (guilds only) to reduce permissions and improve security
- **Persistent Views**: Implements custom UI components with timeout=None for persistent button interactions

## Data Management
- **JSON File Storage**: Uses simple JSON file-based storage (bot_data.json) for persistence
- **In-Memory Operations**: Maintains bot_data as a global variable for fast access during runtime
- **Data Structure**: Organized into four main categories:
  - config: Bot configuration settings
  - active_operations: Currently scheduled operations
  - shifts: Individual shift records
  - shift_totals: Aggregated shift statistics

## User Interface
- **Interactive Buttons**: Custom AttendButton class using discord.ui.View for operation attendance
- **Custom IDs**: Implements persistent custom_id system for button interactions to survive bot restarts
- **Emoji Integration**: Uses emojis in buttons for better visual appeal

## Async Architecture
- **Event-Driven Design**: Built on Discord's async event system
- **Task Scheduling**: Uses discord.ext.tasks for automated periodic functions
- **Non-Blocking Operations**: All bot operations are async to prevent blocking the event loop

# External Dependencies

## Core Dependencies
- **discord.py**: Primary Discord API wrapper library
- **Python Standard Library**: 
  - json: Data serialization and storage
  - asyncio: Asynchronous programming support
  - datetime: Time and date handling
  - os: Operating system interface
  - typing: Type hints and annotations

## Discord Integration
- **Discord API**: Full integration with Discord's REST API and Gateway
- **Discord Slash Commands**: Modern slash command system
- **Discord UI Components**: Interactive buttons and views
- **Discord Intents**: Minimal intent usage for security

## Data Storage
- **File System**: Local JSON file storage for data persistence
- **No External Database**: Self-contained storage solution without external database dependencies