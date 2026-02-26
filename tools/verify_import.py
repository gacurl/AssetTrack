import sqlite3

db = "data/assettrack.db"
con = sqlite3.connect(db)
cur = con.cursor()

print("== Row counts ==")
for t in ["assets", "slots", "holders", "asset_events", "slot_occupancy"]:
    cur.execute(f"select count(*) from {t}")
    print(f"{t}: {cur.fetchone()[0]}")

print("\n== Slot spot-checks ==")
for case in ["CASE-1", "CASE-2", "CASE-10"]:
    cur.execute(
        "select case_name, slot_position, current_asset_tag "
        "from slots where case_name=? order by slot_position limit 5;",
        (case,),
    )
    print(f"{case} first 5:", cur.fetchall())

print("\n== Asset spot-checks ==")
cur.execute(
    "select asset_tag, case_number, slot_number, location_type, custody_state "
    "from assets order by asset_tag limit 10;"
)
print("assets first 10:", cur.fetchall())

print("\n== Sanity checks ==")
cur.execute("select count(*) from assets where location_type != 'STORAGE';")
print("assets not STORAGE:", cur.fetchone()[0])

cur.execute("select count(*) from assets where current_holder_id is not null;")
print("assets with holder set:", cur.fetchone()[0])

cur.execute("select count(*) from slots where current_asset_tag is null;")
print("slots empty:", cur.fetchone()[0])

con.close()
print("\nOK:", db)