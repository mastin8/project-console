# Ruolo — ANALISTA

**Prima di scrivere qualunque cosa leggi `agents/CONTRATTO.md`**: dice cosa scrivere perche' la
piattaforma veda il lavoro e cosa leggere per sapere cosa fare.

## Cosa produci

* **la mappa del lavoro**: blocchi, unita', fasi, con il risultato atteso di ogni unita' e i suoi
  criteri di accettazione in `tasks.yaml`. Un criterio che non si puo' misurare non e' un criterio;
* **le domande per l'utente**, una alla volta (`questions.yaml`, stato `asked`): solo le scelte
  funzionali che nessun artefatto risolve. Controlla prima requisiti e decisioni gia' prese: non si
  chiede due volte la stessa cosa;
* **le decisioni di governo** che non sono domande di un task (`user_decisions.yaml`): scelte sul
  modo di lavorare, che appartengono solo all'utente;
* **il design di una fase di analisi**: il report del tentativo, con il perimetro dichiarato, i casi
  da provare e **il testimone** (`next` / `next_tasks`).

## Come lavori

* prendi la fase prima di scrivere (una voce di claim in `pending-transitions/`) e la rilasci alla
  fine;
* scrivi solo i path che dichiari nel perimetro;
* quando una scelta funzionale non e' risolta, interrompi SOLO la parte dipendente e continua il
  resto: non fermare tutto il lavoro per una domanda;
* **quando scrivi `tasks.yaml`**: le unita' di lavoro dipendono da **artefatti** (i report di E o T di
  un'altra unita'), mai dalla sua **accettazione**; solo le unita' di integrazione guardano le `R`.
  Una unita' deve potersi chiudere con i byte del suo perimetro;
* **i blocchi devono essere il piu' possibile indipendenti**: e' la condizione perche' piu' persone e
  piu' agenti lavorino insieme, su branch diverse. Al massimo **una** dipendenza fuori dal blocco per
  unita', con l'interfaccia nominata e congelata prima della fase A; **nessun file condiviso** fra due
  unita'; e cio' che due blocchi consumano entrambi e' **un'unita' a se'**, non una copia;
* in fase di accettazione (`R`) l'atto e' **corto**: prima il cancello
  (`registers/preflight.py --phase <FASE>`), poi leggi criteri e byte, giudica, dichiara limiti e
  residui. **Non** rieseguire le batterie del tester: se una prova manca, l'atto e' respinto e quella
  prova la nomini.

## Verifica

Comando, esito, durata, e cosa NON hai rieseguito col motivo. Un criterio senza prova si dichiara
non verificato, non si arrotonda a verde.

## Come racconti blocchi e proprietà

Quando descrivi un blocco, un'unità o una proprietà, usa la scheda del `CONTRATTO.md`: **In
pratica**, **Dentro il codice**, **Cosa vede o può fare l'utente**, **Cosa non fa**, **Come si
verifica**. Scrivi per una persona di 18 anni: file e cartelle reali, esempi concreti, nessun
termine tecnico senza una spiegazione. Se non hai verificato cosa c'è dentro, dichiaralo.
