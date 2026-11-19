import os, tempfile
# every test session gets a throwaway audit database
os.environ.setdefault("AUDIT_DB", os.path.join(tempfile.mkdtemp(), "audit_test.db"))
