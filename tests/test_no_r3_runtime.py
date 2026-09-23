"""Static regression guard for the retired individual-result source."""

from pathlib import Path
import os
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_PATTERNS = {
    'scripts': ('*.py',),
    'sql': ('*.sql',),
    'tests': ('*.py',),
}


def active_source_files():
    for directory, patterns in ACTIVE_PATTERNS.items():
        root = PROJECT_ROOT / directory
        for pattern in patterns:
            yield from root.rglob(pattern)


class RetiredResultSourceGuardTests(unittest.TestCase):
    def test_active_python_sql_and_tests_do_not_reference_retired_table(self):
        forbidden = ('brd_' + 'r3').casefold()
        offenders = []
        for path in sorted(active_source_files()):
            text = path.read_text(encoding='utf-8').casefold()
            if forbidden in text:
                offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
        self.assertEqual(
            offenders,
            [],
            'retired result-source table is referenced by active files: '
            + ', '.join(offenders),
        )

    @unittest.skipUnless(os.environ.get('BOATRACE_TEST_DB') == '1',
                         'explicit local DB test opt-in required')
    def test_active_database_views_and_functions_do_not_reference_retired_table(self):
        from scripts.db import target_connection
        forbidden = 'brd_' + 'r3'
        conn = target_connection()
        conn.commit()
        conn.set_session(readonly=True)
        try:
            with conn.cursor() as cur:
                cur.execute('''SELECT schemaname||'.'||viewname AS object_name
                    FROM pg_views WHERE schemaname IN ('raw','core')
                      AND position(%s IN lower(definition))>0
                    UNION ALL
                    SELECT n.nspname||'.'||p.proname
                    FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                    WHERE n.nspname IN ('raw','core') AND p.prokind IN ('f','p')
                      AND position(%s IN lower(pg_get_functiondef(p.oid)))>0''',
                    (forbidden,forbidden))
                self.assertEqual(cur.fetchall(),[])
        finally:
            conn.rollback()
            conn.close()


if __name__ == '__main__':
    unittest.main()
