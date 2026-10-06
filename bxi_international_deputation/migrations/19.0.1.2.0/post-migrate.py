def migrate(cr, version):
    """Link the free text Client / Project to the project of the same name, when exactly one matches."""
    cr.execute("""
        UPDATE bxi_deputation d
           SET project_id = p.id
          FROM project_project p
         WHERE d.project_id IS NULL
           AND d.client_name IS NOT NULL
           AND lower(trim(d.client_name)) = lower(p.name->>'en_US')
           AND (SELECT count(*) FROM project_project p2
                 WHERE lower(p2.name->>'en_US') = lower(trim(d.client_name))) = 1
    """)
