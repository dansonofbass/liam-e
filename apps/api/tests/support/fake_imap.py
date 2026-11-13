"""Recording IMAP server for incremental sync tests."""

class FakeIMAP:
    def __init__(self, uids, validity=7, flags=None):
        self.uids = list(uids)
        self.validity = validity
        self.flags = flags or {}
        self.commands = []

    def login(self, *args):
        self.commands.append(("login", *args))
        return "OK", []

    def select(self, *args, **kwargs):
        self.commands.append(("select", *args))
        return "OK", [str(len(self.uids)).encode()]

    def response(self, name):
        return name, [str(self.validity).encode()]

    def list(self, *args):
        return "OK", []

    def capability(self):
        return "OK", [b"IMAP4rev1"]

    def uid(self, command, *args):
        self.commands.append((command.lower(), *args))
        if command.lower() == "search":
            return "OK", [b" ".join(str(uid).encode() for uid in self.uids)]
        selected = args[0].decode() if isinstance(args[0], bytes) else str(args[0])
        lo, _, hi = selected.partition(":")
        uids = [uid for uid in self.uids if int(lo) <= uid <= int(hi or lo)]
        result = []
        for uid in uids:
            flags = self.flags.get(uid, "")
            header = f"{uid} (UID {uid} FLAGS ({flags}) RFC822.SIZE 25".encode()
            if "BODY.PEEK" in str(args[1]):
                result.append((header + b" BODY[] {25}", b"Subject: test\r\n\r\nbody"))
                result.append(b")")
            else:
                result.append(header + b")")
        return "OK", result

    def logout(self):
        return "BYE", []
