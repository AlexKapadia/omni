-- Per-segment speaker identity: 'me' for the enrolled user, '1'/'2'/… for others.
ALTER TABLE transcript_segments ADD COLUMN speaker_id TEXT NOT NULL DEFAULT '1';
