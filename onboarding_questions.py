#!/usr/bin/env python3
"""Catalogo dell'intervista iniziale: domande raggruppate, adattive e tracciabili."""
from __future__ import annotations

import re
from collections import OrderedDict

SCHEMA = "project-console-onboarding-interview/1.0"
CLOSED = {"answered", "not_applicable", "accepted_risk", "deferred"}
ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9-]{1,31}$")


def _area(prefix, title, prompts):
    return tuple(
        {
            "id": f"{prefix}{index:02d}",
            "area": title,
            "question": question,
            "blocking": True,
            "status": "open",
            "answer": "",
        }
        for index, question in enumerate(prompts, start=1)
    )


QUESTION_BANK = (
    *_area(
        "PROD",
        "Prodotto e risultato",
        (
            "Quale risultato concreto deve esistere alla fine, spiegato con un esempio d'uso?",
            "Come viene gestito oggi lo stesso lavoro e quali passaggi manuali vogliamo eliminare?",
            "Quale cambiamento osservabile dimostrerà che il progetto ha funzionato?",
            "Cosa succede all'organizzazione se il prodotto sbaglia, è lento o non è disponibile?",
            "Quali risultati non sono prioritari, anche se sarebbero utili?",
            "Quali condizioni devono essere vere perché una persona possa dire «per me è finito»?",
        ),
    ),
    *_area(
        "USERS",
        "Persone, ruoli e carichi",
        (
            "Quali tipi di persona useranno il prodotto e con quale frequenza?",
            "Qual è il ruolo principale e quale percorso deve completare più spesso?",
            "Ci sono utenti esperti, principianti o persone con bisogni di accessibilità diversi?",
            "Per ogni ruolo, cosa può vedere, creare, modificare, approvare ed eliminare?",
            "Esistono utenti esterni, ospiti, amministratori o persone che operano per conto di altri?",
            "Quante persone useranno il prodotto insieme e in quali momenti della giornata?",
        ),
    ),
    *_area(
        "FLOW",
        "Percorsi operativi",
        (
            "Qual è il primo percorso completo che deve funzionare dall'inizio alla fine?",
            "Chi o cosa avvia quel percorso e quali informazioni servono prima di iniziare?",
            "Quali passaggi deve compiere l'utente e dove deve poter tornare indietro o correggere?",
            "Quale risultato viene salvato e come l'utente verifica che sia stato salvato davvero?",
            "Cosa deve accadere dopo: notifica, passaggio a un altro ruolo, stampa, export o nuova schermata?",
            "Se l'utente interrompe o ricarica la pagina a metà, come riprende senza perdere o duplicare il lavoro?",
        ),
    ),
    *_area(
        "SCOPE",
        "Perimetro e priorità",
        (
            "Quali funzioni sono indispensabili nella v1, non soltanto desiderabili?",
            "Quali funzioni sono esplicitamente fuori perimetro?",
            "Quali funzioni restano future e da quale condizione dipendono?",
            "Quali vincoli economici, temporali, organizzativi o normativi vanno rispettati?",
            "Il codice esistente va conservato, completato, sostituito in parte o riscritto?",
            "Quali cartelle, dati o integrazioni preesistenti non devono essere toccati?",
        ),
    ),
    *_area(
        "DATA",
        "Dati e modello del dominio",
        (
            "Quali sono gli oggetti principali del prodotto e come li spiegherebbe un utente?",
            "Quale informazione identifica in modo univoco ogni oggetto e quando può cambiare?",
            "Quali relazioni, gerarchie o appartenenze non si possono mai sbagliare?",
            "Quali dati devono restare nello storico e quali possono essere modificati o cancellati?",
            "Quali campi sono obbligatori, unici, calcolati o dipendono da altri campi?",
            "Quanti dati esistono oggi e quanto possono crescere nei primi mesi?",
        ),
    ),
    *_area(
        "RULES",
        "Regole e cambi di stato",
        (
            "Quali regole di business non possono mai essere violate?",
            "Quali stati attraversa un oggetto e quali passaggi sono consentiti?",
            "Quali validazioni devono fermare l'utente prima del salvataggio?",
            "Servono approvazioni, quattro occhi, deleghe o separazione tra chi richiede e chi autorizza?",
            "Cosa deve succedere se due persone modificano lo stesso oggetto nello stesso momento?",
            "Come vanno gestiti calcoli, arrotondamenti, valute, fusi orari o periodi di validità?",
        ),
    ),
    *_area(
        "ACCESS",
        "Accesso, permessi e audit",
        (
            "Come effettua l'accesso ogni ruolo e quali metodi sono ammessi?",
            "Quali ruoli, livelli territoriali, organizzazioni o reparti delimitano ciò che è visibile?",
            "Quali deleghe o sostituzioni temporanee devono esistere e chi le revoca?",
            "Quale controllo va ripetuto su ogni lettura e scrittura, oltre al nascondere pulsanti?",
            "Quali azioni devono finire nell'audit e quali informazioni deve contenere ogni registrazione?",
            "Come vengono revocati accessi, sessioni e permessi quando una persona cambia ruolo o lascia l'organizzazione?",
        ),
    ),
    *_area(
        "SEC",
        "Privacy, sicurezza e dati sensibili",
        (
            "Quali dati sono personali, riservati o particolarmente sensibili?",
            "Chi può vedere i valori completi e quando devono essere mascherati?",
            "Per quanto vanno conservati, esportati, corretti o cancellati i dati?",
            "Dove saranno custoditi segreti, chiavi, password e credenziali dei servizi?",
            "Quali rischi introducono upload, file pubblici, link condivisibili o esportazioni?",
            "Cosa deve vedere l'utente e cosa deve essere registrato quando una sicurezza fallisce?",
        ),
    ),
    *_area(
        "UX",
        "Interfaccia, lingue e accessibilità",
        (
            "In quale contesto viene usato il prodotto: scrivania, telefono, rete locale o uso sul campo?",
            "Quale tono visuale e quale riferimento d'uso deve seguire l'interfaccia?",
            "Quali informazioni e azioni devono essere sempre visibili nella schermata principale?",
            "Come devono essere organizzati menu, gerarchie e passaggi per evitare tabelle indistinte?",
            "Cosa deve mostrare l'interfaccia quando non ci sono dati, sta caricando, ha un errore o è offline?",
            "Quali lingue, formati, requisiti da tastiera, contrasto e supporto mobile sono obbligatori?",
        ),
    ),
    *_area(
        "INT",
        "Integrazioni e comunicazioni",
        (
            "Quali servizi esterni devono essere collegati nella v1?",
            "Per ogni servizio, in quale direzione viaggiano i dati e quale autenticazione usa?",
            "Servono email, SMS, notifiche, pagamenti, calendari, storage o webhook?",
            "Come vanno gestiti timeout, retry, duplicati, richieste ripetute e conciliazione?",
            "Cosa vede l'utente quando un servizio esterno non risponde o completa solo in parte?",
            "Quali ambienti di prova, sandbox, limiti del provider o costi vanno dichiarati?",
        ),
    ),
    *_area(
        "QUALITY",
        "Qualità, test e criteri di accettazione",
        (
            "Quali comportamenti richiedono test automatici e quali richiedono una prova manuale?",
            "Quali comandi, dati di prova e ambienti devono essere usati per verificare il lavoro?",
            "Quali test browser o mobile sono obbligatori e in quali casi?",
            "Quali prestazioni, volumi, tempi di risposta o disponibilità sono accettabili?",
            "Quali difetti non devono mai regredire senza bloccare la consegna?",
            "Quale prova concreta deve poter vedere la persona che accetta?",
        ),
    ),
    *_area(
        "OPS",
        "Ambienti, pubblicazione e continuità",
        (
            "Quali ambienti esistono o devono esistere: locale, test, rete interna, produzione?",
            "Dove verrà eseguito il prodotto e con quali servizi o dipendenze di sistema?",
            "Come funzionano backup, ripristino e verifica periodica della copia?",
            "Quali log, metriche, avvisi e controlli di stato sono necessari?",
            "Come vengono applicate e annullate migrazioni o modifiche di release?",
            "Quali dati dimostrativi vanno creati e quali dati reali non devono mai essere usati in prova?",
        ),
    ),
    *_area(
        "TECH",
        "Architettura e stack",
        (
            "Quale stack è confermato e quale parte deve essere scelta durante il progetto?",
            "Quali responsabilità hanno frontend, backend, API e processi in background?",
            "Quali database, code, cache, scheduler o servizi infrastrutturali servono?",
            "Quali sistemi operativi, browser, runtime e versioni minime vanno supportati?",
            "Quali librerie, provider o dipendenze sono vietati e per quale motivo?",
            "Quale struttura di repository, migrazioni e file generati deve essere mantenuta?",
        ),
    ),
    *_area(
        "DELIVERY",
        "Piano, revisione e stop rule",
        (
            "Quanti task devono comporre il piano e quale dimensione massima deve avere ciascuno?",
            "Quali incrementi devono essere visibili all'utente e quali sono soltanto fondamenta tecniche?",
            "Quali gruppi possono andare in parallelo senza toccare gli stessi file?",
            "Quali percorsi, modelli, migrazioni, permessi o contratti devono restare sempre seriali?",
            "Ogni quanti task si ferma il lavoro per la revisione umana?",
            "Dopo quanti tentativi falliti si ferma il lavoro e quali alternative può scegliere l'utente?",
        ),
    ),
    *_area(
        "AGENT",
        "Verifica, consegna e governo",
        (
            "Chi verifica senza aver scritto gli stessi byte e quali prove deve produrre?",
            "Quali campi devono comparire in ogni report, inclusi test, Git e usage?",
            "Quali skill o competenze servono, in quali task e come si verifica che siano state usate bene?",
            "Quali decisioni restano esclusivamente umane e non possono essere prese dagli agenti?",
            "Cosa accade se il piano o la Costituzione devono cambiare dopo l'approvazione?",
            "Chi firma l'accettazione finale e quali evidenze deve controllare?",
        ),
    ),
)


def initial_questions():
    return [dict(question) for question in QUESTION_BANK]


def merge(existing):
    """Ripete il catalogo senza cancellare risposte già registrate."""
    precedenti = {
        str(item.get("id")): item
        for item in existing or []
        if isinstance(item, dict)
    }
    fuse = []
    for domanda in initial_questions():
        prima = precedenti.get(domanda["id"], {})
        if prima.get("status") in CLOSED | {"open"}:
            domanda["status"] = prima["status"]
        domanda["answer"] = str(prima.get("answer") or "")
        fuse.append(domanda)
    catalogo = {domanda["id"] for domanda in fuse}
    for identifier, prima in precedenti.items():
        if identifier in catalogo:
            continue
        extra = dict(prima)
        extra["status"] = (
            prima.get("status")
            if prima.get("status") in CLOSED | {"open"}
            else "open"
        )
        extra["answer"] = str(prima.get("answer") or "")
        extra["id"] = identifier
        extra["area"] = str(prima.get("area") or "Approfondimenti")
        extra["question"] = str(prima.get("question") or "Domanda senza testo")
        extra["blocking"] = prima.get("blocking") is not False
        fuse.append(extra)
    return fuse


def add_question(questions, area, question, identifier=None, blocking=True):
    """Aggiunge un approfondimento senza imporre un numero massimo di domande."""
    voci = [dict(item) for item in questions or []]
    testo = str(question or "").strip()
    if not testo:
        raise ValueError("la nuova domanda non può essere vuota")
    if any(str(item.get("question") or "").strip() == testo for item in voci):
        raise ValueError("la stessa domanda è già presente")
    esistenti = {str(item.get("id")) for item in voci}
    if identifier:
        nuovo_id = str(identifier).strip().upper()
        if not ID_PATTERN.match(nuovo_id):
            raise ValueError("l'id deve iniziare con una lettera e usare solo A-Z, 0-9 e -")
        if nuovo_id in esistenti:
            raise ValueError(f"esiste già una domanda con id {nuovo_id}")
    else:
        numero = 1
        while f"EXT{numero:02d}" in esistenti:
            numero += 1
        nuovo_id = f"EXT{numero:02d}"
    voci.append(
        {
            "id": nuovo_id,
            "area": str(area or "Approfondimenti").strip() or "Approfondimenti",
            "question": testo,
            "blocking": bool(blocking),
            "status": "open",
            "answer": "",
        }
    )
    return voci


def open_required(questions):
    return [
        question
        for question in questions or []
        if question.get("status") == "open" and question.get("blocking") is True
    ]


def summary(questions):
    totale = len(questions or [])
    chiuse = sum(1 for item in questions or [] if item.get("status") in CLOSED)
    return {"total": totale, "closed": chiuse, "open": totale - chiuse}


def render_markdown(questions):
    dati = summary(questions)
    righe = [
        "# Intervista iniziale",
        "",
        "> Generata dal catalogo di project-console. L'agente pone le domande in gruppi di una o",
        "> due, saltando soltanto ciò che è già dimostrato dalla repository. Ogni domanda deve",
        "> essere chiusa con una risposta o con un motivo esplicito. Le 90 voci iniziali non sono",
        "> un tetto: ogni nuovo ramo viene aggiunto con `--ask-question`.",
        "",
        f"**Stato:** {dati['closed']} chiuse su {dati['total']} · {dati['open']} ancora aperte.",
        "",
    ]
    aree = OrderedDict()
    for domanda in questions or []:
        aree.setdefault(domanda.get("area") or "Altre decisioni", []).append(domanda)
    for area, voci in aree.items():
        righe += [f"## {area}", ""]
        for voce in voci:
            segno = "x" if voce.get("status") in CLOSED else " "
            stato = (
                ""
                if voce.get("status") == "open"
                else f" — **{voce.get('status')}:** {voce.get('answer') or 'senza nota'}"
            )
            righe.append(f"- [{segno}] `{voce.get('id')}` {voce.get('question')}{stato}")
        righe.append("")
    return "\n".join(righe).rstrip() + "\n"
