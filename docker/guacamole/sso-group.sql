-- Every Guacamole account (SSO users are auto-created at first sign-in) joins
-- the group "qure-laptop-users", which may use the Qure laptop connection.
-- Applied by setup.sh after the connection exists. Idempotent.

INSERT INTO guacamole_entity (name, type)
VALUES ('qure-laptop-users', 'USER_GROUP')
ON CONFLICT DO NOTHING;

INSERT INTO guacamole_user_group (entity_id)
SELECT entity_id FROM guacamole_entity
WHERE name = 'qure-laptop-users' AND type = 'USER_GROUP'
ON CONFLICT DO NOTHING;

INSERT INTO guacamole_connection_permission (entity_id, connection_id, permission)
SELECT e.entity_id, c.connection_id, 'READ'
FROM guacamole_entity e, guacamole_connection c
WHERE e.name = 'qure-laptop-users' AND e.type = 'USER_GROUP'
  AND c.connection_name = 'Qure laptop (MinXray / qTrack)'
ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION imladris_add_to_qure_group() RETURNS trigger AS $$
BEGIN
    INSERT INTO guacamole_user_group_member (user_group_id, member_entity_id)
    SELECT g.user_group_id, NEW.entity_id
    FROM guacamole_user_group g
    JOIN guacamole_entity e ON e.entity_id = g.entity_id
    WHERE e.name = 'qure-laptop-users' AND e.type = 'USER_GROUP'
    ON CONFLICT DO NOTHING;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS imladris_qure_group ON guacamole_user;
CREATE TRIGGER imladris_qure_group AFTER INSERT ON guacamole_user
    FOR EACH ROW EXECUTE FUNCTION imladris_add_to_qure_group();
