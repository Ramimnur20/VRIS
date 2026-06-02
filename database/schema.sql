-- VOTOX Database Schema

-- Fun Cog Tables
CREATE TABLE IF NOT EXISTS image_search_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    query TEXT NOT NULL,
    image_data TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_image_search_user_query ON image_search_cache(user_id, query);

-- Owner Cog Tables
CREATE TABLE IF NOT EXISTS owner_dev_whitelist (
    user_id INTEGER PRIMARY KEY
);

-- Uwulock Cog Tables
CREATE TABLE IF NOT EXISTS uwulocked_targets (
    guild_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    is_role BOOLEAN NOT NULL,
    PRIMARY KEY (guild_id, target_id, is_role)
);
CREATE TABLE IF NOT EXISTS uwulock_settings (
    guild_id INTEGER PRIMARY KEY,
    enabled BOOLEAN DEFAULT 1,
    link_blocking BOOLEAN DEFAULT 0,
    invite_blocking BOOLEAN DEFAULT 0
);
CREATE TABLE IF NOT EXISTS uwulock_whitelist (
    guild_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    is_role BOOLEAN NOT NULL,
    PRIMARY KEY (guild_id, target_id, is_role)
);
CREATE TABLE IF NOT EXISTS uwulock_link_whitelist (
    guild_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    is_role BOOLEAN NOT NULL,
    PRIMARY KEY (guild_id, target_id, is_role)
);
CREATE TABLE IF NOT EXISTS uwulock_invite_whitelist (
    guild_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    is_role BOOLEAN NOT NULL,
    PRIMARY KEY (guild_id, target_id, is_role)
);

-- Autorole Cog Tables
CREATE TABLE IF NOT EXISTS autorole_config (
    guild_id INTEGER PRIMARY KEY,
    humans_role_id INTEGER,
    bots_role_id INTEGER,
    both_role_id INTEGER,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- AFK Cog Tables
CREATE TABLE IF NOT EXISTS afk_users (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL PRIMARY KEY,
    reason TEXT,
    original_nick TEXT,
    timestamp INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS afk_ignored_channels (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);
CREATE TABLE IF NOT EXISTS afk_log_channels (
    guild_id INTEGER NOT NULL PRIMARY KEY,
    channel_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS afk_presets (
    user_id INTEGER NOT NULL,
    preset_name TEXT NOT NULL,
    preset_status TEXT,
    PRIMARY KEY (user_id, preset_name)
);
CREATE TABLE IF NOT EXISTS afk_settings (
    guild_id INTEGER NOT NULL PRIMARY KEY,
    timeout_minutes INTEGER DEFAULT 0
);

-- Moderation Cog Tables
CREATE TABLE IF NOT EXISTS warnings (
    warning_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    reason TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS lockdown_channels (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);
CREATE TABLE IF NOT EXISTS snipe_protected_channels (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);
CREATE TABLE IF NOT EXISTS snipe_protected_users (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

-- AutoMod Cog Tables (Combined with Fun Cog requirements)
CREATE TABLE IF NOT EXISTS automod_settings (
    guild_id INTEGER PRIMARY KEY,
    emoji_limit INTEGER DEFAULT 0,
    line_limit INTEGER DEFAULT 0,
    log_channel_id INTEGER DEFAULT NULL,
    blocked_words TEXT,
    word_filter INTEGER DEFAULT 0
);

-- Logging Cog Tables
CREATE TABLE IF NOT EXISTS logging_config (
    guild_id INTEGER PRIMARY KEY,
    enabled INTEGER DEFAULT 0,
    channels TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Giveaway Cog Tables
CREATE TABLE IF NOT EXISTS giveaways (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL PRIMARY KEY,
    prize TEXT NOT NULL,
    winners INTEGER DEFAULT 1,
    end_time TEXT NOT NULL,
    host_id INTEGER NOT NULL,
    status TEXT DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS giveaway_config (
    guild_id INTEGER PRIMARY KEY,
    config TEXT
);

-- Prefix Cog Tables
CREATE TABLE IF NOT EXISTS guild_prefixes (
    guild_id INTEGER,
    prefix TEXT,
    PRIMARY KEY (guild_id, prefix)
);
CREATE TABLE IF NOT EXISTS user_prefixes (
    user_id INTEGER PRIMARY KEY,
    prefix TEXT
);
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id INTEGER PRIMARY KEY,
    no_prefix_enabled INTEGER DEFAULT 0
);

-- Media Cog Tables
CREATE TABLE IF NOT EXISTS media_channel_config (
    guild_id INTEGER PRIMARY KEY,
    allow_links INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS media_channels (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);
CREATE TABLE IF NOT EXISTS media_bypass_users (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

-- Level Cog Tables
CREATE TABLE IF NOT EXISTS level_settings (
    guild_id INTEGER PRIMARY KEY,
    enabled INTEGER DEFAULT 0,
    xp_per_message INTEGER DEFAULT 15,
    cooldown_seconds INTEGER DEFAULT 60
);
CREATE TABLE IF NOT EXISTS level_users (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    xp INTEGER DEFAULT 0,
    level INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS level_roles (
    guild_id INTEGER NOT NULL,
    level INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, level)
);

-- Greet & Leave Cog Tables
CREATE TABLE IF NOT EXISTS welcome_config (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER,
    message TEXT,
    embed_enabled INTEGER DEFAULT 0,
    embed_title TEXT,
    embed_image TEXT,
    embed_footer TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS leave_config (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER,
    message TEXT,
    embed_enabled INTEGER DEFAULT 0,
    embed_title TEXT,
    embed_image TEXT,
    embed_footer TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Autoresponder Cog Tables
CREATE TABLE IF NOT EXISTS autoresponder_config (
    guild_id INTEGER PRIMARY KEY,
    triggers TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS autoreact_config (
    guild_id INTEGER PRIMARY KEY,
    triggers TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Social Cog Tables
CREATE TABLE IF NOT EXISTS youtube_feeds (
    guild_id INTEGER NOT NULL,
    youtube_channel_url TEXT NOT NULL,
    discord_channel_id INTEGER NOT NULL,
    last_video_id TEXT,
    PRIMARY KEY (guild_id, youtube_channel_url)
);
CREATE TABLE IF NOT EXISTS youtube_roles (
    guild_id INTEGER NOT NULL,
    youtube_channel_url TEXT NOT NULL,
    role_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, youtube_channel_url, role_id)
);