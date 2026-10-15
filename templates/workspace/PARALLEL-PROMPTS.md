# Il quaderno dei prompt

Ogni sezione NUMERATA di questo file e' un prompt pronto da incollare in una chat nuova. Il
coordinatore ne ricava lo stato da solo, senza che nessuno lo scriva a mano, leggendo tre cose:

1. il **codice di riconoscimento**: il nome della voce di claim o dell'obbligo che il testo nomina
   («esiste la voce di claim ES01T», «l'obbligo ES01-EXPORT»). Deve esistere nel registro;
2. la **consegna**: una riga `CONSEGNA:` col percorso del file che il prompt deve pubblicare,
   sotto il prefisso dichiarato (`deliverable_prefix`, per convenzione `reports/`);
3. il **titolo scritto a mano**, che il coordinatore confronta con la misura e di cui dichiara il
   disaccordo invece di crederci.

Da li' esce lo stato: **fatto** (la consegna esiste su disco), **in azione** (la voce di claim e'
viva), **da lanciare**, **consegna respinta** (consegnata e la verifica ha detto di no),
**ignoto** (nessun codice riconoscibile: si dichiara, non si inventa).

---

## 1 — ES01A — DA FARE

Sostituisci questo esempio col primo prompt vero.

```
Lavora in <percorso del progetto>. Sei un agente di esecuzione: non coordinare, non chiedere
conferme, non dispatchare figli.

Il tuo incarico e' scritto per intero in <file del mandato>: leggilo tutto prima di ogni altra
cosa.

REGISTRO: in state.yaml esiste la voce di claim ES01A. NON scrivere il registro a mano: deposita
in pending-transitions/ la presa (formato in quella cartella, README.md) con taken_by = il tuo
nome canonico, PRIMA del primo byte, e la richiesta di rilascio alla fine. Se un'altra corsia l'ha
gia' presa, fermati e dillo.

VERIFICA: prova SOLO cio' che tocchi, UNA volta, subito prima di consegnare. Dichiara comando,
esito, durata e cio' che NON hai rieseguito, col motivo.

CONSEGNA: reports/ES01A/attempt-1.yaml (verifica che NON esista) e il puntatore reports/ES01A.yaml.
```
