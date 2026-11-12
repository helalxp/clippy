from __future__ import annotations

import asyncio
from types import SimpleNamespace


def test_job_edit_lock_serializes_mutations_for_the_same_job():
    import app as app_module

    async def scenario():
        entered = []
        release_first = asyncio.Event()
        second_entered = asyncio.Event()

        @app_module._serialize_job_edit
        async def mutate(req):
            entered.append(req.job_id)
            if len(entered) == 1:
                await release_first.wait()
            else:
                second_entered.set()
            return len(entered)

        first = asyncio.create_task(mutate(SimpleNamespace(job_id="same-job")))
        await asyncio.sleep(0)
        second = asyncio.create_task(mutate(SimpleNamespace(job_id="same-job")))
        await asyncio.sleep(0)

        assert entered == ["same-job"]
        assert not second_entered.is_set()

        release_first.set()
        first_result, second_result = await asyncio.gather(first, second)
        assert first_result == 1
        assert second_result == 2
        assert second_entered.is_set()

    asyncio.run(scenario())


def test_job_edit_lock_does_not_block_an_independent_job():
    import app as app_module

    async def scenario():
        entered = set()
        release = asyncio.Event()

        @app_module._serialize_job_edit
        async def mutate(req):
            entered.add(req.job_id)
            if req.job_id == "job-a":
                await release.wait()
            return req.job_id

        first = asyncio.create_task(mutate(SimpleNamespace(job_id="job-a")))
        await asyncio.sleep(0)
        second = asyncio.create_task(mutate(SimpleNamespace(job_id="job-b")))
        second_result = await asyncio.wait_for(second, timeout=1)

        assert second_result == "job-b"
        assert entered == {"job-a", "job-b"}

        release.set()
        assert await first == "job-a"

    asyncio.run(scenario())


def test_job_edit_lock_accepts_form_style_job_id_keyword():
    import app as app_module

    async def scenario():
        @app_module._serialize_job_edit
        async def mutate(request, *, job_id):
            return job_id

        assert await mutate(SimpleNamespace(), job_id="form-job") == "form-job"

    asyncio.run(scenario())
