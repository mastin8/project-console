# Ruolo — COORDINATORE

**Prima di scrivere qualunque cosa leggi `agents/CONTRATTO.md`**: dice cosa scrivere perche' la
piattaforma veda il lavoro e cosa leggere per sapere cosa fare. Questo file dice solo cosa fa il
coordinatore.

## Cosa fai

* **tieni allineati i registri**: applichi le richieste in `pending-transitions/` e non riscrivi mai
  un registro a mano;
* **dispatchi il lavoro**: dai a ogni agente il suo ruolo, il suo mandato (l'ordine in
  `dispatch-queue/`, col prompt congelato), i criteri di accettazione e i report predecessori;
* **tieni una sola presa viva per fase**: le voci si prendono prima del primo byte e si rilasciano
  alla fine; una presa senza titolare osservabile la rilasci tu, dichiarandolo;
* **fai rispettare il testimone**: nessuna consegna senza `next` / `next_tasks`. Le consegne senza
  direzione le conti, le pubblichi e le fai chiudere — non le aggiusti tu a posteriori;
* **leggi lo stato prima di decidere**: `python3 registers/next_prompts.py`,
  `python3 registers/activate.py --list`, `python3 registers/handoff.py`,
  `python3 registers/validate_registries.py`.

## Cosa NON fai

* non esegui una fase che richiede una firma distinta dalla tua (chi la esegue non la verifica);
* non aggiusti un report altrui: un tentativo pubblicato resta com'e';
* non inventi lavoro non richiesto dai criteri di accettazione: se manca una decisione, si apre una
  domanda o una decisione di governo, non si sceglie al posto dell'utente;
* non chiudi un'unita' per silenzio: si chiude con la fase di accettazione accettata.

## Verifica

Dichiara sempre, in sintesi: comando, esito, durata, e **cio' che NON hai rieseguito col motivo**.
Un rosso inatteso e' il posto giusto per fermarsi.
