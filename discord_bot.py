import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import asyncio
from datetime import datetime, timedelta
import os
from typing import Optional, cast

# Bot setup - using only non-privileged intents for slash commands
intents = discord.Intents.default()
intents.guilds = True
intents.members = True  # Enable to detect new members for welcome messages

bot = commands.Bot(command_prefix='!', intents=intents)

# Data storage
DATA_FILE = 'bot_data.json'

def load_data():
    """Load bot data from JSON file"""
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            'config': {},
            'active_operations': {},
            'shifts': {},
            'shift_totals': {},
            'usernames': {}
        }

def save_data(data):
    """Save bot data to JSON file"""
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2, default=str)

# Global data variable
bot_data = load_data()

class AttendButton(discord.ui.View):
    def __init__(self, operation_id):
        super().__init__(timeout=None)
        self.operation_id = operation_id
        
        # Set custom_id after button creation for persistence
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.label == 'Attend':
                item.custom_id = f"attend_operation_{operation_id}"

    @discord.ui.button(label='Attend', style=discord.ButtonStyle.green, emoji='✋')
    async def attend_operation(self, interaction: discord.Interaction, button: discord.ui.Button):
        global bot_data
        
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        
        guild = interaction.guild
        user = interaction.user
        
        # Get member object
        member = user if isinstance(user, discord.Member) else guild.get_member(user.id)
        if member is None:
            await interaction.response.send_message("Could not find your member information.", ephemeral=True)
            return
        
        # Get operation data
        if self.operation_id not in bot_data['active_operations']:
            await interaction.response.send_message("This operation is no longer active.", ephemeral=True)
            return
        
        operation_data = bot_data['active_operations'][self.operation_id]
        
        # Check if user is already attending
        if str(user.id) in operation_data['attendees']:
            await interaction.response.send_message("You are already attending this operation!", ephemeral=True)
            return
        
        # Check if operation is at max capacity
        if operation_data.get('max_attendees') and len(operation_data['attendees']) >= operation_data['max_attendees']:
            await interaction.response.send_message("This operation is at maximum capacity!", ephemeral=True)
            return
        
        # Add user to attendees and store username for leaderboard
        operation_data['attendees'][str(user.id)] = {
            'username': member.display_name,
            'joined_at': datetime.now().isoformat()
        }
        
        # Store username for future leaderboard use
        guild_id_str = str(guild.id)
        if guild_id_str not in bot_data.setdefault('usernames', {}):
            bot_data['usernames'][guild_id_str] = {}
        bot_data['usernames'][guild_id_str][str(user.id)] = member.display_name
        
        # Give user the operation role
        role_name = f"Operation_{operation_data['date']}"
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            role = await guild.create_role(name=role_name, color=discord.Color.blue())
        
        await member.add_roles(role)
        
        # Update the embed with all operation info
        embed_description = f"**Airport:** {operation_data['airport']}\n**Time:** {operation_data['time']}\n**Date:** {operation_data['date']}"
        
        if operation_data.get('operation_type'):
            embed_description += f"\n**Type:** {operation_data['operation_type']}"
        if operation_data.get('description'):
            embed_description += f"\n**Description:** {operation_data['description']}"
        if operation_data.get('max_attendees'):
            embed_description += f"\n**Max Attendees:** {operation_data['max_attendees']}"
        
        embed = discord.Embed(
            title="📢 OPERATION ACTIVE",
            description=embed_description,
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        
        attendees_list = []
        for attendee_data in operation_data['attendees'].values():
            attendees_list.append(f"• {attendee_data['username']}")
        
        # Show attendee count with capacity if applicable
        attendee_count = len(attendees_list)
        max_attendees = operation_data.get('max_attendees')
        
        if max_attendees:
            attendee_header = f"Attendees ({attendee_count}/{max_attendees})"
        else:
            attendee_header = f"Attendees ({attendee_count})"
        
        if attendees_list:
            embed.add_field(name=attendee_header, value="\n".join(attendees_list), inline=False)
        else:
            embed.add_field(name=attendee_header, value="No attendees yet", inline=False)
        
        embed.set_footer(text="ATC24 PTFS Ground Crew")
        
        # Update the message
        await interaction.response.edit_message(embed=embed, view=self)
        
        # Save data
        save_data(bot_data)
        
        # Send confirmation
        await interaction.followup.send(f"You have successfully joined the operation! You now have the {role.name} role.", ephemeral=True)

class ShiftManageView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label='Add Time', style=discord.ButtonStyle.green)
    async def add_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AddTimeModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label='Remove Time', style=discord.ButtonStyle.red)
    async def remove_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = RemoveTimeModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label='End Shift', style=discord.ButtonStyle.secondary)
    async def end_shift(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EndShiftModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label='Update Leaderboard', style=discord.ButtonStyle.primary)
    async def update_leaderboard(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.send_leaderboard_update(interaction)

    async def send_leaderboard_update(self, interaction):
        global bot_data
        
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        
        config = bot_data['config'].get(str(interaction.guild.id), {})
        leaderboard_channel_id = config.get('leaderboard_channel')
        
        if not leaderboard_channel_id:
            await interaction.response.send_message("Leaderboard channel not configured. Use /setup first.", ephemeral=True)
            return
        
        channel = bot.get_channel(leaderboard_channel_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Leaderboard channel not found or is not a text channel.", ephemeral=True)
            return
        
        # Generate leaderboard
        leaderboard_embed = await generate_leaderboard_embed(interaction.guild)
        
        # Send or update leaderboard message
        async for message in channel.history(limit=10):
            if (message.author == bot.user and message.embeds and 
                message.embeds[0].title and "Shift Time Leaderboard" in message.embeds[0].title):
                await message.edit(embed=leaderboard_embed)
                await interaction.response.send_message("Leaderboard updated!", ephemeral=True)
                return
        
        await channel.send(embed=leaderboard_embed)
        await interaction.response.send_message("New leaderboard posted!", ephemeral=True)

class AddTimeModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Add Time to User")
        
        self.user_input = discord.ui.TextInput(
            label="User (mention or ID)",
            placeholder="@username or user ID",
            required=True
        )
        self.time_input = discord.ui.TextInput(
            label="Time to add (in minutes)",
            placeholder="60",
            required=True
        )
        
        self.add_item(self.user_input)
        self.add_item(self.time_input)

    async def on_submit(self, interaction: discord.Interaction):
        global bot_data
        
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        
        try:
            # Parse user
            user_str = self.user_input.value.strip()
            if user_str.startswith('<@') and user_str.endswith('>'):
                user_id = int(user_str[2:-1].replace('!', ''))
            else:
                user_id = int(user_str)
            
            user = interaction.guild.get_member(user_id)
            if not user:
                await interaction.response.send_message("User not found.", ephemeral=True)
                return
            
            # Store username for leaderboard
            guild_id = str(interaction.guild.id)
            user_id_str = str(user_id)
            if guild_id not in bot_data.setdefault('usernames', {}):
                bot_data['usernames'][guild_id] = {}
            bot_data['usernames'][guild_id][user_id_str] = user.display_name
            
            # Parse time
            minutes = int(self.time_input.value)
            
            if guild_id not in bot_data['shift_totals']:
                bot_data['shift_totals'][guild_id] = {}
            
            if user_id_str not in bot_data['shift_totals'][guild_id]:
                bot_data['shift_totals'][guild_id][user_id_str] = 0
            
            bot_data['shift_totals'][guild_id][user_id_str] += minutes
            save_data(bot_data)
            
            await interaction.response.send_message(f"Added {minutes} minutes to {user.display_name}'s total time.", ephemeral=True)
            
        except ValueError:
            await interaction.response.send_message("Invalid input. Please check your values.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

class RemoveTimeModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Remove Time from User")
        
        self.user_input = discord.ui.TextInput(
            label="User (mention or ID)",
            placeholder="@username or user ID",
            required=True
        )
        self.time_input = discord.ui.TextInput(
            label="Time to remove (in minutes)",
            placeholder="60",
            required=True
        )
        
        self.add_item(self.user_input)
        self.add_item(self.time_input)

    async def on_submit(self, interaction: discord.Interaction):
        global bot_data
        
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        
        try:
            # Parse user
            user_str = self.user_input.value.strip()
            if user_str.startswith('<@') and user_str.endswith('>'):
                user_id = int(user_str[2:-1].replace('!', ''))
            else:
                user_id = int(user_str)
            
            user = interaction.guild.get_member(user_id)
            if not user:
                await interaction.response.send_message("User not found.", ephemeral=True)
                return
            
            # Store username for leaderboard
            guild_id = str(interaction.guild.id)
            user_id_str = str(user_id)
            if guild_id not in bot_data.setdefault('usernames', {}):
                bot_data['usernames'][guild_id] = {}
            bot_data['usernames'][guild_id][user_id_str] = user.display_name
            
            # Parse time
            minutes = int(self.time_input.value)
            
            if guild_id not in bot_data['shift_totals']:
                bot_data['shift_totals'][guild_id] = {}
            
            if user_id_str not in bot_data['shift_totals'][guild_id]:
                bot_data['shift_totals'][guild_id][user_id_str] = 0
            
            bot_data['shift_totals'][guild_id][user_id_str] = max(0, bot_data['shift_totals'][guild_id][user_id_str] - minutes)
            save_data(bot_data)
            
            await interaction.response.send_message(f"Removed {minutes} minutes from {user.display_name}'s total time.", ephemeral=True)
            
        except ValueError:
            await interaction.response.send_message("Invalid input. Please check your values.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

class EndShiftModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="End User's Shift")
        
        self.user_input = discord.ui.TextInput(
            label="User (mention or ID)",
            placeholder="@username or user ID",
            required=True
        )
        
        self.add_item(self.user_input)

    async def on_submit(self, interaction: discord.Interaction):
        global bot_data
        
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        
        try:
            # Parse user
            user_str = self.user_input.value.strip()
            if user_str.startswith('<@') and user_str.endswith('>'):
                user_id = int(user_str[2:-1].replace('!', ''))
            else:
                user_id = int(user_str)
            
            user = interaction.guild.get_member(user_id)
            if not user:
                await interaction.response.send_message("User not found.", ephemeral=True)
                return
            
            # Store username for leaderboard
            guild_id = str(interaction.guild.id)
            user_id_str = str(user_id)
            if guild_id not in bot_data.setdefault('usernames', {}):
                bot_data['usernames'][guild_id] = {}
            bot_data['usernames'][guild_id][user_id_str] = user.display_name
            
            if guild_id in bot_data['shifts'] and user_id_str in bot_data['shifts'][guild_id]:
                shift_data = bot_data['shifts'][guild_id][user_id_str]
                start_time = datetime.fromisoformat(shift_data['start_time'])
                end_time = datetime.now()
                duration = int((end_time - start_time).total_seconds() / 60)
                
                # Add to total time
                if guild_id not in bot_data['shift_totals']:
                    bot_data['shift_totals'][guild_id] = {}
                if user_id_str not in bot_data['shift_totals'][guild_id]:
                    bot_data['shift_totals'][guild_id][user_id_str] = 0
                
                bot_data['shift_totals'][guild_id][user_id_str] += duration
                
                # Remove from active shifts
                del bot_data['shifts'][guild_id][user_id_str]
                save_data(bot_data)
                
                await interaction.response.send_message(f"Ended {user.display_name}'s shift. Duration: {duration} minutes.", ephemeral=True)
            else:
                await interaction.response.send_message(f"{user.display_name} doesn't have an active shift.", ephemeral=True)
            
        except ValueError:
            await interaction.response.send_message("Invalid input. Please check your values.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

async def generate_leaderboard_embed(guild):
    global bot_data
    guild_id = str(guild.id)
    
    if guild_id not in bot_data['shift_totals']:
        bot_data['shift_totals'][guild_id] = {}
    
    # Sort users by total time
    user_times = bot_data['shift_totals'][guild_id]
    sorted_users = sorted(user_times.items(), key=lambda x: x[1], reverse=True)
    
    embed = discord.Embed(
        title="📊 Shift Time Leaderboard",
        color=discord.Color.gold(),
        timestamp=datetime.now()
    )
    
    if not sorted_users:
        embed.description = "No shift data available yet."
        return embed
    
    leaderboard_text = ""
    for i, (user_id, total_minutes) in enumerate(sorted_users[:10]):
        user = guild.get_member(int(user_id))
        
        # Try to get username from stored usernames first, then current member, then fallback
        stored_usernames = bot_data.get('usernames', {}).get(guild_id, {})
        if user:
            username = user.display_name
            # Update stored username if member is found
            if guild_id not in bot_data.setdefault('usernames', {}):
                bot_data['usernames'][guild_id] = {}
            bot_data['usernames'][guild_id][user_id] = username
            save_data(bot_data)
        elif user_id in stored_usernames:
            username = stored_usernames[user_id]
        else:
            username = f"User {user_id}"
        
        hours = total_minutes // 60
        minutes = total_minutes % 60
        
        if i == 0:
            emoji = "🥇"
        elif i == 1:
            emoji = "🥈"
        elif i == 2:
            emoji = "🥉"
        else:
            emoji = f"{i+1}."
        
        leaderboard_text += f"{emoji} **{username}** - {hours}h {minutes}m\n"
    
    embed.description = leaderboard_text
    embed.set_footer(text="ATC24 PTFS Ground Crew")
    
    return embed

@tasks.loop(minutes=1)
async def update_all_status_boards():
    """Update all status boards every minute"""
    global bot_data
    for guild_id, config in bot_data.get('config', {}).items():
        if config.get('status_board_channel'):
            guild = bot.get_guild(int(guild_id))
            if guild:
                await update_status_board_for_guild(guild)

@bot.event
async def on_ready():
    print(f'{bot.user} has logged in!')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    
    # Register persistent views for button persistence across restarts
    # This allows buttons to work even after bot restarts
    for operation_id in bot_data.get('active_operations', {}).keys():
        view = AttendButton(operation_id)
        bot.add_view(view)
    
    # Start the status board update loop
    if not update_all_status_boards.is_running():
        update_all_status_boards.start()
        print("Started status board update loop")

@bot.event
async def on_member_join(member):
    """Welcome new members to the server"""
    global bot_data
    config = bot_data['config'].get(str(member.guild.id), {})
    welcome_channel_id = config.get('welcome_channel')
    
    if not welcome_channel_id:
        return
    
    channel = bot.get_channel(welcome_channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    
    embed = discord.Embed(
        title="🎉 Welcome to ATC24 PTFS Ground Crew!",
        description=f"Welcome {member.mention}! We're excited to have you join our ground crew team.",
        color=discord.Color.green(),
        timestamp=datetime.now()
    )
    
    embed.add_field(
        name="📚 Getting Started",
        value="Use `/links` to access the Ground Crew Guide and important resources.",
        inline=False
    )
    
    embed.add_field(
        name="⏰ Shift Management",
        value="Use `/shift` to start working and track your hours.",
        inline=False
    )
    
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="ATC24 PTFS Ground Crew")
    
    await channel.send(embed=embed)

# Admin check decorator - using built-in has_permissions
# This replaces the custom is_admin check to avoid type issues

@bot.tree.command(name="setup", description="Configure bot settings (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
@app_commands.describe(
    operation_role="Role to ping for operations",
    operation_channel="Channel for operation announcements",
    leaderboard_channel="Channel for leaderboard updates",
    status_board_channel="Channel for live status board",
    welcome_channel="Channel for welcome messages"
)
async def setup(
    interaction: discord.Interaction, 
    operation_role: discord.Role, 
    operation_channel: discord.TextChannel, 
    leaderboard_channel: discord.TextChannel,
    status_board_channel: Optional[discord.TextChannel] = None,
    welcome_channel: Optional[discord.TextChannel] = None
):
    global bot_data
    
    # Guild is guaranteed to exist due to @app_commands.guild_only()
    assert interaction.guild is not None
    guild_id = str(interaction.guild.id)
    
    if guild_id not in bot_data['config']:
        bot_data['config'][guild_id] = {}
    
    config_updates = {
        'operation_role_id': operation_role.id,
        'operation_channel_id': operation_channel.id,
        'leaderboard_channel': leaderboard_channel.id
    }
    
    if status_board_channel:
        config_updates['status_board_channel'] = status_board_channel.id
    
    if welcome_channel:
        config_updates['welcome_channel'] = welcome_channel.id
    
    bot_data['config'][guild_id].update(config_updates)
    
    save_data(bot_data)
    
    description = f"**Operation Role:** {operation_role.mention}\n**Operation Channel:** {operation_channel.mention}\n**Leaderboard Channel:** {leaderboard_channel.mention}"
    
    if status_board_channel:
        description += f"\n**Status Board Channel:** {status_board_channel.mention}"
    
    if welcome_channel:
        description += f"\n**Welcome Channel:** {welcome_channel.mention}"
    
    embed = discord.Embed(
        title="✅ Setup Complete",
        description=description,
        color=discord.Color.green()
    )
    
    # Post initial status board if configured
    if status_board_channel:
        status_embed = await generate_status_board_embed(interaction.guild)
        message = await status_board_channel.send(embed=status_embed)
        # Store message ID for future updates
        bot_data['config'][guild_id]['status_board_message_id'] = message.id
        save_data(bot_data)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="operation-start", description="Start a new operation (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
@app_commands.describe(
    airport="Airport code", 
    time="Operation time", 
    date="Operation date",
    description="Optional description or notes about the operation",
    max_attendees="Maximum number of attendees (leave blank for unlimited)",
    operation_type="Type of operation (e.g., Training, Event, Regular)"
)
async def operation_start(
    interaction: discord.Interaction, 
    airport: str, 
    time: str, 
    date: str,
    description: Optional[str] = None,
    max_attendees: Optional[int] = None,
    operation_type: Optional[str] = None
):
    # Validate max_attendees
    if max_attendees is not None and max_attendees < 1:
        await interaction.response.send_message("Max attendees must be at least 1.", ephemeral=True)
        return
    global bot_data
    
    # Guild is guaranteed to exist due to @app_commands.guild_only()
    assert interaction.guild is not None
    guild_id = str(interaction.guild.id)
    config = bot_data['config'].get(guild_id, {})
    
    if not config.get('operation_role_id') or not config.get('operation_channel_id'):
        await interaction.response.send_message("Please run /setup first to configure the bot.", ephemeral=True)
        return
    
    # Check if there's already an active operation for this guild
    if any(op_id.startswith(f"{guild_id}_") for op_id in bot_data['active_operations']):
        await interaction.response.send_message("There is already an active operation. Please stop it first with /operation-stop.", ephemeral=True)
        return
    
    # Create operation data
    operation_id = f"{guild_id}_{datetime.now().timestamp()}"
    operation_data = {
        'airport': airport,
        'time': time,
        'date': date,
        'description': description,
        'max_attendees': max_attendees,
        'operation_type': operation_type,
        'started_by': interaction.user.id,
        'started_at': datetime.now().isoformat(),
        'attendees': {}
    }
    
    bot_data['active_operations'][operation_id] = operation_data
    save_data(bot_data)
    
    # Create embed with additional info
    embed_description = f"**Airport:** {airport}\n**Time:** {time}\n**Date:** {date}"
    
    if operation_type:
        embed_description += f"\n**Type:** {operation_type}"
    if description:
        embed_description += f"\n**Description:** {description}"
    if max_attendees:
        embed_description += f"\n**Max Attendees:** {max_attendees}"
    
    embed = discord.Embed(
        title="📢 OPERATION ACTIVE",
        description=embed_description,
        color=discord.Color.green(),
        timestamp=datetime.now()
    )
    embed.add_field(name="Attendees (0)", value="No attendees yet", inline=False)
    embed.set_footer(text="ATC24 PTFS Ground Crew")
    
    # Get role and channel
    role = interaction.guild.get_role(config['operation_role_id'])
    channel = interaction.guild.get_channel(config['operation_channel_id'])
    
    if not role:
        await interaction.response.send_message("Operation role not found. Please run /setup again.", ephemeral=True)
        return
    
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message("Operation channel not found or is not a text channel. Please run /setup again.", ephemeral=True)
        return
    
    # Send message with button
    view = AttendButton(operation_id)
    # Register the view for persistence
    bot.add_view(view)
    message = await channel.send(content=f"{role.mention} New operation starting!", embed=embed, view=view)
    
    await interaction.response.send_message(f"Operation started successfully in {channel.mention}!", ephemeral=True)

@bot.tree.command(name="operation-stop", description="Stop the current operation (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def operation_stop(interaction: discord.Interaction):
    global bot_data
    
    # Guild is guaranteed to exist due to @app_commands.guild_only()
    assert interaction.guild is not None
    guild_id = str(interaction.guild.id)
    config = bot_data['config'].get(guild_id, {})
    
    # Find and stop all active operations for this guild
    operations_to_stop = [op_id for op_id in bot_data['active_operations'].keys() if op_id.startswith(f"{guild_id}_")]
    
    if not operations_to_stop:
        await interaction.response.send_message("No active operation found.", ephemeral=True)
        return
    
    # Stop all operations and clean up roles
    for operation_id in operations_to_stop:
        operation_data = bot_data['active_operations'][operation_id]
        
        # Delete the operation role if it exists
        role_name = f"Operation_{operation_data['date']}"
        role = discord.utils.get(interaction.guild.roles, name=role_name)
        if role:
            await role.delete()
        
        # Remove operation from active operations
        del bot_data['active_operations'][operation_id]
    
    save_data(bot_data)
    
    # Send end message
    channel = interaction.guild.get_channel(config.get('operation_channel_id'))
    if isinstance(channel, discord.TextChannel):
        embed = discord.Embed(
            title="🔴 OPERATION ENDED",
            description="This operation has ended. Thank you all for attending!",
            color=discord.Color.red(),
            timestamp=datetime.now()
        )
        embed.set_footer(text="ATC24 PTFS Ground Crew")
        await channel.send(embed=embed)
    
    await interaction.response.send_message("Operation stopped successfully!", ephemeral=True)

class ShiftManagementView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label='Start Shift', style=discord.ButtonStyle.green, emoji='🟢')
    async def start_shift(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = StartShiftModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label='End Shift', style=discord.ButtonStyle.red, emoji='🔴')
    async def end_shift(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_end_shift(interaction)

    @discord.ui.button(label='Start Break', style=discord.ButtonStyle.secondary, emoji='☕')
    async def start_break(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_start_break(interaction)

    @discord.ui.button(label='End Break', style=discord.ButtonStyle.primary, emoji='▶️')
    async def end_break(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_end_break(interaction)

    async def handle_end_shift(self, interaction):
        global bot_data
        
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
        
        # Check if user is clocked in
        if guild_id not in bot_data['shifts'] or user_id not in bot_data['shifts'][guild_id]:
            await interaction.response.send_message("You are not currently clocked in!", ephemeral=True)
            return
        
        # Calculate shift duration
        shift_data = bot_data['shifts'][guild_id][user_id]
        start_time = datetime.fromisoformat(shift_data['start_time'])
        end_time = datetime.now()
        
        # Account for break time if any
        total_break_time = shift_data.get('total_break_time', 0)
        duration = end_time - start_time
        duration_minutes = int(duration.total_seconds() / 60) - total_break_time
        
        # Add to total time
        if guild_id not in bot_data['shift_totals']:
            bot_data['shift_totals'][guild_id] = {}
        if user_id not in bot_data['shift_totals'][guild_id]:
            bot_data['shift_totals'][guild_id][user_id] = 0
        
        bot_data['shift_totals'][guild_id][user_id] += max(0, duration_minutes)
        
        # Store username
        member = interaction.user if isinstance(interaction.user, discord.Member) else interaction.guild.get_member(interaction.user.id)
        if member:
            if guild_id not in bot_data.setdefault('usernames', {}):
                bot_data['usernames'][guild_id] = {}
            bot_data['usernames'][guild_id][user_id] = member.display_name
        
        # Remove from active shifts
        airport = shift_data['airport']
        del bot_data['shifts'][guild_id][user_id]
        save_data(bot_data)
        
        # Update status board
        await update_status_board_for_guild(interaction.guild)
        
        # Format duration
        hours = duration_minutes // 60
        minutes = duration_minutes % 60
        
        embed = discord.Embed(
            title="⏰ Shift Ended",
            description=f"You have successfully ended your shift at **{airport}**\n\n**Shift Duration:** {hours}h {minutes}m",
            color=discord.Color.red(),
            timestamp=datetime.now()
        )
        embed.set_footer(text="Thanks for your service!")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def handle_start_break(self, interaction):
        global bot_data
        
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
        
        # Check if user is clocked in
        if guild_id not in bot_data['shifts'] or user_id not in bot_data['shifts'][guild_id]:
            await interaction.response.send_message("You need to be clocked in to take a break!", ephemeral=True)
            return
        
        shift_data = bot_data['shifts'][guild_id][user_id]
        
        # Check if already on break
        if shift_data.get('on_break'):
            await interaction.response.send_message("You are already on break!", ephemeral=True)
            return
        
        # Start break
        shift_data['on_break'] = True
        shift_data['break_start'] = datetime.now().isoformat()
        save_data(bot_data)
        
        # Update status board
        await update_status_board_for_guild(interaction.guild)
        
        embed = discord.Embed(
            title="☕ Break Started",
            description="Enjoy your break! Remember to end it when you're back.",
            color=discord.Color.orange(),
            timestamp=datetime.now()
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def handle_end_break(self, interaction):
        global bot_data
        
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
        
        # Check if user is clocked in
        if guild_id not in bot_data['shifts'] or user_id not in bot_data['shifts'][guild_id]:
            await interaction.response.send_message("You need to be clocked in!", ephemeral=True)
            return
        
        shift_data = bot_data['shifts'][guild_id][user_id]
        
        # Check if on break
        if not shift_data.get('on_break'):
            await interaction.response.send_message("You are not currently on break!", ephemeral=True)
            return
        
        # Calculate break duration
        break_start = datetime.fromisoformat(shift_data['break_start'])
        break_end = datetime.now()
        break_duration = int((break_end - break_start).total_seconds() / 60)
        
        # Add to total break time
        if 'total_break_time' not in shift_data:
            shift_data['total_break_time'] = 0
        shift_data['total_break_time'] += break_duration
        
        # End break
        shift_data['on_break'] = False
        del shift_data['break_start']
        save_data(bot_data)
        
        # Update status board
        await update_status_board_for_guild(interaction.guild)
        
        embed = discord.Embed(
            title="▶️ Break Ended",
            description=f"Welcome back! Your break lasted {break_duration} minutes.",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


class StartShiftModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Start Your Shift")
        
        self.airport_input = discord.ui.TextInput(
            label="Airport",
            placeholder="Enter airport code (e.g., KJFK, EGLL)",
            required=True,
            max_length=10
        )
        
        self.add_item(self.airport_input)

    async def on_submit(self, interaction: discord.Interaction):
        global bot_data
        
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
        airport = self.airport_input.value.strip().upper()
        
        # Initialize data structures if needed
        if guild_id not in bot_data['shifts']:
            bot_data['shifts'][guild_id] = {}
        
        # Check if user is already clocked in
        if user_id in bot_data['shifts'][guild_id]:
            await interaction.response.send_message("You are already clocked in! Use 'End Shift' to finish your current shift first.", ephemeral=True)
            return
        
        # Get member for display_name and store username
        member = interaction.user if isinstance(interaction.user, discord.Member) else interaction.guild.get_member(interaction.user.id)
        display_name = member.display_name if member else interaction.user.name
        
        if guild_id not in bot_data.setdefault('usernames', {}):
            bot_data['usernames'][guild_id] = {}
        bot_data['usernames'][guild_id][user_id] = display_name
        
        # Clock in the user
        bot_data['shifts'][guild_id][user_id] = {
            'airport': airport,
            'start_time': datetime.now().isoformat(),
            'username': display_name,
            'on_break': False,
            'total_break_time': 0
        }
        
        save_data(bot_data)
        
        # Update status board
        await update_status_board_for_guild(interaction.guild)
        
        embed = discord.Embed(
            title="⏰ Shift Started",
            description=f"You have successfully started your shift at **{airport}**",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        embed.set_footer(text="Have a great shift!")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def generate_status_board_embed(guild):
    global bot_data
    guild_id = str(guild.id)
    
    active_shifts = bot_data['shifts'].get(guild_id, {})
    
    embed = discord.Embed(
        title="📊 Live Status Board",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    
    if not active_shifts:
        embed.description = "No one is currently on shift."
        embed.set_footer(text="ATC24 PTFS Ground Crew • Updates automatically")
        return embed
    
    on_duty = []
    on_break = []
    
    for user_id, shift_data in active_shifts.items():
        user = guild.get_member(int(user_id))
        username = user.display_name if user else shift_data.get('username', f'User {user_id}')
        
        start_time = datetime.fromisoformat(shift_data['start_time'])
        duration = datetime.now() - start_time
        duration_minutes = int(duration.total_seconds() / 60)
        hours = duration_minutes // 60
        minutes = duration_minutes % 60
        
        shift_info = f"• **{username}** at {shift_data['airport']} ({hours}h {minutes}m)"
        
        if shift_data.get('on_break'):
            break_start = datetime.fromisoformat(shift_data['break_start'])
            break_duration = int((datetime.now() - break_start).total_seconds() / 60)
            shift_info += f" - *Break: {break_duration}m*"
            on_break.append(shift_info)
        else:
            on_duty.append(shift_info)
    
    if on_duty:
        embed.add_field(name=f"🟢 On Duty ({len(on_duty)})", value="\n".join(on_duty), inline=False)
    
    if on_break:
        embed.add_field(name=f"☕ On Break ({len(on_break)})", value="\n".join(on_break), inline=False)
    
    embed.set_footer(text="ATC24 PTFS Ground Crew • Updates automatically")
    return embed

async def update_status_board_for_guild(guild):
    """Update the status board for a specific guild"""
    global bot_data
    config = bot_data['config'].get(str(guild.id), {})
    status_board_channel_id = config.get('status_board_channel')
    status_board_message_id = config.get('status_board_message_id')
    
    if not status_board_channel_id:
        return
    
    channel = bot.get_channel(status_board_channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    
    # Generate new status board embed
    embed = await generate_status_board_embed(guild)
    
    # Try to edit existing message first
    if status_board_message_id:
        try:
            message = await channel.fetch_message(status_board_message_id)
            await message.edit(embed=embed)
            return
        except (discord.NotFound, discord.HTTPException):
            # Message was deleted or not found, create new one
            pass
    
    # Create new status board message
    message = await channel.send(embed=embed)
    # Store new message ID
    bot_data['config'][str(guild.id)]['status_board_message_id'] = message.id
    save_data(bot_data)

# Remove old clock commands - they are now replaced by the shift management interface

@bot.tree.command(name="shift", description="Manage your shift (start, end, breaks)")
@app_commands.guild_only()
async def shift_management(interaction: discord.Interaction):
    view = ShiftManagementView()
    
    embed = discord.Embed(
        title="🔧 Shift Management",
        description="Choose an option below to manage your shift:",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    embed.add_field(name="🟢 Start Shift", value="Begin working at an airport", inline=True)
    embed.add_field(name="🔴 End Shift", value="Finish your current shift", inline=True)
    embed.add_field(name="☕ Start Break", value="Take a break (pauses shift timer)", inline=True)
    embed.add_field(name="▶️ End Break", value="Resume work after break", inline=True)
    embed.set_footer(text="ATC24 PTFS Ground Crew")
    
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name="links", description="Get useful links for ATC24 PTFS Ground Crew")
@app_commands.guild_only()
async def links_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🔗 ATC24 PTFS Ground Crew Links",
        description="Here are the essential links for our ground crew operations:",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    
    embed.add_field(
        name="📚 Ground Crew Guide",
        value="[Click here to access the guide](https://drive.google.com/file/d/1a7ek3QyG4efP2GQNdH3pwk_aOdNL8GYY/view?usp=sharing)",
        inline=False
    )
    
    embed.add_field(
        name="✈️ My Plane",
        value="[Click here to access My Plane](https://myplane.onrender.com)",
        inline=False
    )
    
    embed.set_footer(text="ATC24 PTFS Ground Crew")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="shift-manage", description="Manage shifts (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def shift_manage(interaction: discord.Interaction):
    global bot_data
    
    # Guild is guaranteed to exist due to @app_commands.guild_only()
    assert interaction.guild is not None
    guild_id = str(interaction.guild.id)
    
    # Get active shifts
    active_shifts = bot_data['shifts'].get(guild_id, {})
    
    embed = discord.Embed(
        title="🔧 Shift Management Dashboard",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    
    if active_shifts:
        shift_list = []
        for user_id, shift_data in active_shifts.items():
            user = interaction.guild.get_member(int(user_id))
            username = user.display_name if user else f"User {user_id}"
            start_time = datetime.fromisoformat(shift_data['start_time'])
            duration = datetime.now() - start_time
            duration_minutes = int(duration.total_seconds() / 60)
            hours = duration_minutes // 60
            minutes = duration_minutes % 60
            
            shift_list.append(f"• **{username}** at {shift_data['airport']} ({hours}h {minutes}m)")
        
        embed.add_field(name=f"Active Shifts ({len(active_shifts)})", value="\n".join(shift_list), inline=False)
    else:
        embed.add_field(name="Active Shifts (0)", value="No active shifts", inline=False)
    
    embed.set_footer(text="Use the buttons below to manage shifts")
    
    view = ShiftManageView()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name="leaderboard", description="Show shift time leaderboard")
@app_commands.guild_only()
async def leaderboard(interaction: discord.Interaction):
    embed = await generate_leaderboard_embed(interaction.guild)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Error handler for missing permissions
@setup.error
@operation_start.error
@operation_stop.error
@shift_manage.error
async def admin_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You need administrator permissions to use this command.", ephemeral=True)
    elif isinstance(error, app_commands.NoPrivateMessage):
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
    else:
        await interaction.response.send_message(f"An error occurred: {str(error)}", ephemeral=True)

# Run the bot
if __name__ == "__main__":
    token = os.getenv('DISCORD_BOT_TOKEN')
    if not token:
        print("Please set the DISCORD_BOT_TOKEN environment variable")
    else:
        bot.run(token)