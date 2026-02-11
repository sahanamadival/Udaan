-- SQL Migration for Google Auth Implementation

-- Create indexes for email uniqueness (this helps enforce uniqueness)
CREATE UNIQUE INDEX IF NOT EXISTS idx_students_email ON students(email) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_teachers_email ON teachers(email) WHERE email IS NOT NULL;

-- Add google_auth column to students table
ALTER TABLE students ADD COLUMN google_auth INTEGER DEFAULT 0;

-- Add google_auth column to teachers table  
ALTER TABLE teachers ADD COLUMN google_auth INTEGER DEFAULT 0;

-- Update existing records to have NULL password_hash where it's empty or 'google_oauth'
UPDATE students SET password_hash = NULL WHERE password_hash = 'google_oauth';
UPDATE teachers SET password_hash = NULL WHERE password_hash = 'google_oauth';