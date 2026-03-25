DISPOSABLE = {
    "mailinator.com","guerrillamail.com","tempmail.com","throwaway.email",
    "yopmail.com","sharklasers.com","guerrillamailblock.com","grr.la",
    "guerrillamail.info","guerrillamail.net","guerrillamail.org","guerrillamail.de",
    "trashmail.com","trashmail.me","trashmail.net","temp-mail.org",
    "fakeinbox.com","tempail.com","dispostable.com","maildrop.cc",
    "mailnesia.com","mailcatch.com","mailsac.com","10minutemail.com",
    "mohmal.com","burnermail.io","inboxkitten.com","getnada.com",
    "tmail.ws","harakirimail.com","33mail.com","maildrop.cc",
    "discard.email","mailpoof.com","filzmail.com","clipmail.eu",
    "getairmail.com","crazymailing.com","mailforspam.com","tempr.email",
    "disposableemailaddresses.emailmiser.com","mailzilla.com",
    "armyspy.com","cuvox.de","dayrep.com","einrot.com","fleckens.hu",
    "gustr.com","jourrapide.com","rhyta.com","superrito.com","teleworm.us",
    "tempomail.fr","tittbit.in","trashinbox.com","trashymail.com",
    "yopmail.fr","cool.fr.nf","jetable.fr.nf","courriel.fr.nf",
    "moncourrier.fr.nf","speed.1s.fr","nospam.ze.tc","kurzepost.de",
    "objectmail.com","proxymail.eu","rcpt.at","trash-mail.at",
    "trashmail.at","wegwerfmail.de","wegwerfmail.net","wegwerfmail.org",
    "wh4f.org","mailexpire.com","tempinbox.com","givmail.com",
    "mailme.lv","spam4.me","guerrillamail.biz","binkmail.com",
    "safetymail.info","spamgourmet.com","mytrashmail.com","mailinater.com",
    "mailinator.net","mailinator2.com","reallymymail.com","veryday.ch",
    "veryrealemail.com","emailigo.de","spamspot.com",
}

def check(email):
    try:
        if "@" not in email:
            return {"error": "Invalid email format - missing @"}
        domain = email.strip().lower().split("@")[-1]
        return {"email": email, "domain": domain, "is_disposable": domain in DISPOSABLE, "blocklist_size": len(DISPOSABLE)}
    except Exception as e:
        return {"error": str(e)}
