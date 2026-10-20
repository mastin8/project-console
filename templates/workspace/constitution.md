---
schema: project-console-constitution/1.0
status: draft
project: "__PROJECT__"
updated_at: ""
approved_at: ""
approved_sha256: ""
---

# Constitution del progetto

> Questa è la scheda che l'agente compila con l'utente **prima** di creare task o scrivere codice.
> Resta `draft` finché l'utente non conferma il piano nella pagina **Costituzione** del console.
> L'agente non approva mai il documento. Dopo l'approvazione il file diventa immutabile e il
> console verifica la sua impronta SHA-256 a ogni lettura.

## 1. Obiettivo

<!-- In due o tre frasi: cosa deve esistere alla fine e per chi. -->

## 2. Fuori perimetro

<!-- Cosa non fa parte di questo progetto, anche se sembra correlato. -->

## 3. Stack tecnico

<!-- Linguaggi, framework, database, infrastruttura, test, deploy.
     Se una scelta è ancora aperta, scrivilo qui e fai la domanda. -->

## 4. Deliverable finale

<!-- Il risultato concreto che l'utente può usare: applicazione, documento, sito, API,
     pacchetto, automazione. Definisci cosa significa "finito". -->

## 5. Ampiezza e numero dei task

<!-- Quanti task, quanto grandi, quanti file al massimo per task.
     Preferisci fette verticali utilizzabili a pezzi tecnici isolati.
     Indica cosa può andare in parallelo e cosa deve restare seriale. -->

## 6. Skill e agenti

<!-- Quali skill/competenze servono, in quali task, e quali non vanno usate.
     Se una skill non esiste, dichiaralo invece di inventarla. -->

## 7. Flusso di lavoro

<!-- Come si lavora: normale o rigorosa, A/E/T/R o fasi diverse,
     chi prende in carico, chi verifica, chi accetta, come si consegna. -->

## 8. Parallelismo

<!-- Gruppi di task indipendenti e file/cartelle che non devono essere toccati
     da due mani insieme. Il parallelismo è consentito solo se i percorsi non si sovrappongono. -->

## 9. Test e accettazione

<!-- Test obbligatori per tipo di task, comandi, durata, fixture.
     Cosa deve vedere l'utente per accettare. Un test non eseguito si dichiara. -->

## 10. Rischi e modalità rigorosa

<!-- Dati, sicurezza, migrazioni, release, file condivisi, integrazioni esterne.
     Quali task entrano automaticamente in modalità rigorosa. -->

## 11. Stop rule

<!-- Dopo quanti tentativi falliti ci si ferma e si chiede una decisione.
     Cosa può decidere l'utente: cambiare perimetro, accettare un limite, riprovare. -->

## 12. Domande e risposte dell'onboarding

<!-- Una riga per domanda, con la risposta dell'utente e la data.
     Le domande senza risposta restano visibili: non si inventano. -->

## Approvazione

- [ ] L'utente ha confermato obiettivo e fuori perimetro.
- [ ] L'utente ha confermato stack e deliverable.
- [ ] L'utente ha confermato numero/ampiezza dei task e parallelismo.
- [ ] L'utente ha confermato test, accettazione, rischi e stop rule.
- [ ] L'utente ha controllato la bozza nella pagina Costituzione ed è pronto ad approvarla.

> L'approvazione avviene **solo dal front-end**. Dopo il clic su «Approva e blocca» il documento
> non è più riformabile: nessun agente e nessuna pagina possono modificarlo.
