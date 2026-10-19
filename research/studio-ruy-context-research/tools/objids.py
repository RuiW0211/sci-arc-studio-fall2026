"""List ProPublica object IDs for an EIN, newest first."""
import re, subprocess, sys
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
def ids(ein):
    p = f"org_{ein}.html"
    subprocess.run(["curl","-sL","--compressed","-m","40","-A",UA,"-o",p,
                    f"https://projects.propublica.org/nonprofits/organizations/{ein}"], check=True)
    t = open(p, encoding="utf-8", errors="ignore").read()
    out, seen = [], set()
    for m in re.finditer(r'display_990/\d+/IRS%2F\d+_(\d{6})_(990[A-Z]*)_[^"]*"[\s\S]{0,400}?download-xml\?object_id=(\d+)', t):
        key = m.group(3)
        if key not in seen:
            seen.add(key); out.append((m.group(1), m.group(2), key))
    for m in re.finditer(r'download-xml\?object_id=(\d+)', t):
        if m.group(1) not in seen:
            seen.add(m.group(1)); out.append(("?", "?", m.group(1)))
    return out
if __name__ == "__main__":
    for period, form, oid in ids(sys.argv[1]):
        print(period, form, oid)
