def migrate(cr, version):
    """The office employees work from when the Regular Office is introduced is their regular office."""
    cr.execute("""
        UPDATE hr_employee emp
           SET conveyance_regular_location_id = ver.work_location_id
          FROM hr_version ver
         WHERE ver.id = emp.current_version_id
           AND emp.conveyance_regular_location_id IS NULL
           AND ver.work_location_id IS NOT NULL
    """)
