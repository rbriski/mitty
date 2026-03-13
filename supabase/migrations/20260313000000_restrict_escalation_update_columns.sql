-- Restrict escalation_log UPDATE to only acknowledged + acknowledged_at columns.
-- Previously the UPDATE policy allowed modifying any column, which could let
-- users tamper with signal_type, concept, or context_data.

REVOKE UPDATE ON escalation_log FROM authenticated;
GRANT UPDATE (acknowledged, acknowledged_at) ON escalation_log TO authenticated;
