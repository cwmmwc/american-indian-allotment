-- Measured confirmation of patent_persons foreign keys on Cloud SQL.
-- Expect: 3 FK rows (one referencing rails_patents); orphan_patent_id = 0.
SELECT conname, confrelid::regclass AS references
  FROM pg_constraint
 WHERE conrelid = 'patent_persons'::regclass AND contype = 'f'
 ORDER BY conname;

SELECT COUNT(*) AS orphan_patent_id
  FROM patent_persons pp
  LEFT JOIN rails_patents rp ON rp.id = pp.patent_id
 WHERE rp.id IS NULL;
