from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Replace the free text Client and Project / Business Objective with projects.

    The text is linked to the project of the same name when exactly one matches, and the
    Client then comes from that project. Other text is kept in the justification, since the
    old columns are dropped at the end of the upgrade.
    """
    cr.execute("""
        INSERT INTO bxi_eb_assignment_project_rel (assignment_id, project_id)
        SELECT a.id, p.id
          FROM bxi_eb_assignment a
          JOIN project_project p ON lower(p.name->>'en_US') = lower(trim(a.project_reference))
         WHERE a.project_reference IS NOT NULL
           AND (SELECT count(*) FROM project_project p2
                 WHERE lower(p2.name->>'en_US') = lower(trim(a.project_reference))) = 1
        ON CONFLICT DO NOTHING
        RETURNING assignment_id
    """)
    assignment_ids = [row[0] for row in cr.fetchall()]
    cr.execute("""
        UPDATE bxi_eb_assignment
           SET justification = concat_ws(E'\n', nullif(justification, ''),
                                         'Client: ' || nullif(trim(client_name), ''),
                                         'Project / Business Objective: ' || nullif(trim(project_reference), ''))
         WHERE NOT id = ANY(%s)
           AND (nullif(trim(client_name), '') IS NOT NULL OR nullif(trim(project_reference), '') IS NOT NULL)
    """, [assignment_ids])
    if assignment_ids:
        env = api.Environment(cr, SUPERUSER_ID, {})
        assignments = env['bxi.eb.assignment'].browse(assignment_ids)
        env.add_to_compute(assignments._fields['client_id'], assignments)
        assignments.flush_recordset(['client_id'])
