"""Worker STA: serialização, propagação de exceção, encerramento."""

import threading

import pytest

from swmcp.com.worker import ComWorker, WorkerClosedError


@pytest.fixture
def worker():
    w = ComWorker(init=lambda: None, teardown=lambda: None)
    yield w
    w.close()


def test_executa_no_mesmo_thread_sempre(worker):
    threads = {worker.run(lambda: threading.current_thread().name) for _ in range(20)}
    assert len(threads) == 1
    assert threads.pop() == "sw-com-worker"


def test_resultado_e_excecao_propagam(worker):
    assert worker.run(lambda: 21 * 2) == 42

    def boom():
        raise ValueError("falha proposital")

    with pytest.raises(ValueError, match="falha proposital"):
        worker.run(boom)


def test_chamadas_serializadas_em_ordem(worker):
    resultados = []
    futures = [worker.submit(lambda i=i: resultados.append(i)) for i in range(50)]
    for f in futures:
        f.result()
    assert resultados == list(range(50))


def test_submit_apos_close_falha():
    w = ComWorker(init=lambda: None, teardown=lambda: None)
    w.close()
    with pytest.raises(WorkerClosedError):
        w.submit(lambda: None)


def test_init_e_teardown_rodam_no_thread():
    eventos = []
    w = ComWorker(init=lambda: eventos.append("init"), teardown=lambda: eventos.append("teardown"))
    w.run(lambda: eventos.append("trabalho"))
    w.close()
    assert eventos == ["init", "trabalho", "teardown"]
