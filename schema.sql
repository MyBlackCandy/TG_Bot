CREATE TABLE IF NOT EXISTS users_subscription (
    user_id BIGINT PRIMARY KEY,
    username TEXT,
    expiry_date TIMESTAMP WITH TIME ZONE,
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS group_permissions (
    id SERIAL PRIMARY KEY,
    group_id BIGINT,
    user_id BIGINT,
    username TEXT,
    role TEXT, -- 'owner' หรือ 'helper'
    UNIQUE(group_id, user_id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id SERIAL PRIMARY KEY,
    group_id BIGINT,
    user_id BIGINT,
    username TEXT,
    amount INT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
