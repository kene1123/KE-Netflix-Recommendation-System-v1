CREATE TABLE IF NOT EXISTS movies (
    movie_id INT PRIMARY KEY,
    title TEXT,
    genres TEXT
);

CREATE TABLE IF NOT EXISTS users (
    user_id SERIAL PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_activity (
    id SERIAL PRIMARY KEY,
    user_id INT,
    movie_id INT,
    watch_time FLOAT,
    rating FLOAT,
    timestamp TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recommendations (
    id SERIAL PRIMARY KEY,
    user_id INT,
    movie_id INT,
    score FLOAT,
    algorithm_type TEXT,
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS model_metrics (
    id SERIAL PRIMARY KEY,
    model_name TEXT,
    precision_at_k FLOAT,
    rmse FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);