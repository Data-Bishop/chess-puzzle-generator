-- Initialize the chess puzzles database

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Jobs table: tracks puzzle generation jobs
CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,

    -- Optional filters (for Phase 5)
    date_from DATE,
    date_to DATE,
    min_rating INTEGER,
    max_rating INTEGER,
    time_control VARCHAR(50),

    -- Metadata
    total_games INTEGER DEFAULT 0,
    total_puzzles INTEGER DEFAULT 0
);

-- Puzzles table: stores generated puzzles
CREATE TABLE IF NOT EXISTS puzzles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    fen VARCHAR(255) NOT NULL,
    solution JSONB NOT NULL, -- Array of moves in UCI format
    theme VARCHAR(100), -- e.g., "fork", "pin", "discovered_attack"
    rating INTEGER, -- Estimated puzzle difficulty
    game_url VARCHAR(500), -- Link to original Chess.com game
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP + INTERVAL '24 hours')
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_jobs_username ON jobs(username);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_puzzles_job_id ON puzzles(job_id);
CREATE INDEX IF NOT EXISTS idx_puzzles_expires_at ON puzzles(expires_at);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger to auto-update updated_at on jobs table
CREATE TRIGGER update_jobs_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Function to delete expired puzzles (for cron job later)
CREATE OR REPLACE FUNCTION delete_expired_puzzles()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM puzzles WHERE expires_at < CURRENT_TIMESTAMP;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ language 'plpgsql';
