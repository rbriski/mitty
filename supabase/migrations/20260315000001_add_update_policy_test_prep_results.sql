-- Add UPDATE RLS policy for test_prep_results so users can update their own answers
CREATE POLICY "Users can update own test prep results"
    ON test_prep_results FOR UPDATE
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);
