# La posta in arrivo

Qui si deposita **un messaggio per file**, intero e come è arrivato.

Perché esiste: la presa, il rilascio e il `next` del report la piattaforma li legge dai registri.
Tutto il resto di quello che un agente scrive — cosa ha consegnato, cosa non ha fatto, cosa serve
dopo, cosa ha scoperto per strada — vive in una chat, e una chat non è un archivio. Questa cartella
è il posto dove quel messaggio non muore.

## Com'è fatto un file

Nome: `<AAAAmmgg>T<HHMMSS>-<fase>.md` — la fase è la parola dopo il timestamp, e può mancare.
Contenuto: quattro righe di intestazione fra due `---`, e sotto il messaggio **parola per parola**.

```markdown
---
ricevuta: 20261016T101500-A11Y03R
received_at: '2026-10-16T10:15:00+02:00'
sender: /root/nav03r2
phase: A11Y03R
unit: A11Y03
kind: consegna
---

Il messaggio, senza tagliare niente e senza riscriverlo.
```

`kind`: `consegna` | `direzione` | `decisione` | `nota`. `sender`: la corsia, oppure `utente`.

Un file **senza intestazione** è accettato lo stesso: tutto il file è messaggio. Meglio un
messaggio salvato male che un messaggio perso.

## Come si deposita

```bash
python3 registers/inbox.py --workspace . --add --file messaggio.md --phase A11Y03R --from /root/nova
python3 registers/inbox.py --workspace . --add --text "il testo, anche multilinea" --phase A11Y03R
```

Oppure dalla pagina, in **Posta in arrivo** (pagina *Adesso*): si incolla e si preme un pulsante.
Depositare non tocca i registri: scrive un file, e basta. Per questo non c'è un lock da prendere e
non si può rompere niente di vivo.

## Quando è «lavorata»

Una ricevuta è **lavorata** quando esiste un report di quella fase che *dichiara* una data dopo di
lei (`published_at`). Se nessun report della fase dichiara una data, si ripiega sull'mtime del file.
È una misura, non una promessa — e la data dichiarata è la misura giusta, perché un `git pull` o un
checkout riscrivono l'mtime senza che nessuno abbia lavorato niente, e in quel caso tutte le
ricevute risulterebbero lavorate in un colpo.

Se non riguarda una fase, o se è stata gestita in altro modo, si chiude a mano:

```bash
python3 registers/inbox.py --workspace . --chiudi <ricevuta> --nota "cosa ne è stato"
```

L'elenco di quello che resta da lavorare è in pagina, e anche da riga di comando:

```bash
python3 registers/inbox.py --workspace . --list
```

**La posta non è un registro.** Non si riscrive, non si cancella, non si sposta: una ricevuta è la
memoria di quello che qualcuno ha detto. Se un messaggio è sbagliato, se ne deposita un altro che lo
corregge.
