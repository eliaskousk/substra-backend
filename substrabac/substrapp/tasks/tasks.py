from __future__ import absolute_import, unicode_literals

import os
import shutil
import tempfile
from os import path

from checksumdir import dirhash
from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings
from rest_framework.reverse import reverse

from substrabac.celery import app
from substrapp.utils import get_hash, create_directory, get_remote_file, uncompress_content
from substrapp.ledger_utils import (log_start_tuple, log_success_tuple, log_fail_tuple,
                                    query_tuples, LedgerTimeout, LedgerError)
from substrapp.tasks.utils import ResourcesManager, compute_docker
from substrapp.tasks.exception_handler import compute_error_code

import docker
import json
from multiprocessing.managers import BaseManager

import logging


def get_objective(subtuple):
    from substrapp.models import Objective

    objectiveHash = subtuple['objective']['hash']

    objective = None
    try:
        objective = Objective.objects.get(pk=objectiveHash)
    except ObjectDoesNotExist:
        pass

    # get objective from ledger as it is not available in local db and store it in local db
    if objective is None or not objective.metrics:
        content, computed_hash = get_remote_file(subtuple['objective']['metrics'])

        objective, _ = Objective.objects.update_or_create(pkhash=objectiveHash, validated=True)

        tmp_file = tempfile.TemporaryFile()
        tmp_file.write(content)
        objective.metrics.save('metrics.py', tmp_file)

    return objective


def get_algo(subtuple):
    algo_content, _ = get_remote_file(subtuple['algo'])
    return algo_content


def _get_model(model):
    model_content, _ = get_remote_file(model, model['traintupleKey'])
    return model_content


def get_model(subtuple):
    model = subtuple.get('model')
    if model:
        return _get_model(model)
    else:
        return None


def get_models(subtuple):
    input_models = subtuple.get('inModels')
    if input_models:
        return [_get_model(item) for item in input_models]
    else:
        return []


def _put_model(subtuple, subtuple_directory, model_content, model_hash, traintuple_key):
    if not model_content:
        raise Exception('Model content should not be empty')

    from substrapp.models import Model

    # store a model in local subtuple directory from input model content
    model_dst_path = path.join(subtuple_directory, f'model/{traintuple_key}')
    model = None
    try:
        model = Model.objects.get(pk=model_hash)
    except ObjectDoesNotExist:  # write it to local disk
        with open(model_dst_path, 'wb') as f:
            f.write(model_content)
    else:
        # verify that local db model file is not corrupted
        if get_hash(model.file.path, traintuple_key) != model_hash:
            raise Exception('Model Hash in Subtuple is not the same as in local db')

        if not os.path.exists(model_dst_path):
            os.link(model.file.path, model_dst_path)
        else:
            # verify that local subtuple model file is not corrupted
            if get_hash(model_dst_path, traintuple_key) != model_hash:
                raise Exception('Model Hash in Subtuple is not the same as in local medias')


def put_model(subtuple, subtuple_directory, model_content):
    return _put_model(subtuple, subtuple_directory, model_content, subtuple['model']['hash'],
                      subtuple['model']['traintupleKey'])


def put_models(subtuple, subtuple_directory, models_content):
    if not models_content:
        raise Exception('Models content should not be empty')

    for model_content, model in zip(models_content, subtuple['inModels']):
        _put_model(model, subtuple_directory, model_content, model['hash'], model['traintupleKey'])


def put_opener(subtuple, subtuple_directory):
    from substrapp.models import DataManager
    data_opener_hash = subtuple['dataset']['openerHash']

    datamanager = DataManager.objects.get(pk=data_opener_hash)

    # verify that local db opener file is not corrupted
    if get_hash(datamanager.data_opener.path) != data_opener_hash:
        raise Exception('DataOpener Hash in Subtuple is not the same as in local db')

    opener_dst_path = path.join(subtuple_directory, 'opener/opener.py')
    if not os.path.exists(opener_dst_path):
        os.link(datamanager.data_opener.path, opener_dst_path)
    else:
        # verify that local subtuple data opener file is not corrupted
        if get_hash(opener_dst_path) != data_opener_hash:
            raise Exception('DataOpener Hash in Subtuple is not the same as in local medias')


def put_data_sample(subtuple, subtuple_directory):
    from substrapp.models import DataSample

    for data_sample_key in subtuple['dataset']['keys']:
        data_sample = DataSample.objects.get(pk=data_sample_key)
        data_sample_hash = dirhash(data_sample.path, 'sha256')
        if data_sample_hash != data_sample_key:
            raise Exception('Data Sample Hash in Subtuple is not the same as in local db')

        # create a symlink on the folder containing data
        subtuple_data_directory = path.join(subtuple_directory, 'data', data_sample_key)
        try:
            os.symlink(data_sample.path, subtuple_data_directory)
        except OSError as e:
            logging.exception(e)
            raise Exception('Failed to create sym link for subtuple data sample')


def put_metric(subtuple_directory, objective):
    metrics_dst_path = path.join(subtuple_directory, 'metrics/metrics.py')
    if not os.path.exists(metrics_dst_path):
        os.link(objective.metrics.path, metrics_dst_path)


def put_algo(subtuple_directory, algo_content):
    uncompress_content(algo_content, subtuple_directory)


def build_subtuple_folders(subtuple):
    # create a folder named `subtuple['key']` in /medias/subtuple/ with 5 subfolders opener, data, model, pred, metrics
    subtuple_directory = path.join(getattr(settings, 'MEDIA_ROOT'), 'subtuple', subtuple['key'])
    create_directory(subtuple_directory)

    for folder in ['opener', 'data', 'model', 'pred', 'metrics']:
        create_directory(path.join(subtuple_directory, folder))

    return subtuple_directory


def remove_subtuple_materials(subtuple_directory):
    try:
        shutil.rmtree(subtuple_directory)
    except Exception as e:
        logging.exception(e)


# Instatiate Ressource Manager in BaseManager to share it between celery concurrent tasks
BaseManager.register('ResourcesManager', ResourcesManager)
manager = BaseManager()
manager.start()
resources_manager = manager.ResourcesManager()


@app.task(bind=True, ignore_result=True)
def prepare_training_task(self):
    prepare_task('traintuple')


@app.task(ignore_result=True)
def prepare_testing_task():
    prepare_task('testtuple')


def prepare_task(tuple_type):
    data_owner = get_hash(settings.LEDGER['signcert'])
    worker_queue = f"{settings.LEDGER['name']}.worker"
    tuples = query_tuples(tuple_type, data_owner)

    for subtuple in tuples:
        prepare_tuple.apply_async(
            (subtuple, tuple_type),
            task_id=subtuple['key'],
            queue=worker_queue)


@app.task(ignore_result=False)
def prepare_tuple(subtuple, tuple_type):
    from django_celery_results.models import TaskResult

    fltask = None
    worker_queue = f"{settings.LEDGER['name']}.worker"

    if 'fltask' in subtuple and subtuple['fltask']:
        fltask = subtuple['fltask']
        flresults = TaskResult.objects.filter(
            task_name='substrapp.tasks.tasks.compute_task',
            result__icontains=f'"fltask": "{fltask}"')

        if flresults and flresults.count() > 0:
            worker_queue = json.loads(flresults.first().as_dict()['result'])['worker']

    try:
        compute = True
        try:
            log_start_tuple(tuple_type, subtuple['key'])
        except LedgerTimeout:
            pass
        except LedgerError as e:
            # Do not log_fail_tuple in this case, because prepare_tuple task are not unique
            # in case of multiple instances of substrabac running for the same organisation
            # So prepare_tuple tasks are ignored if it cannot log_start_tuple
            # TODO: find a way to handle this special case to avoid silent failure in other cases.
            logging.exception(e)
            compute = False

        if compute:
            compute_task.apply_async(
                (tuple_type, subtuple, fltask),
                queue=worker_queue)

    except Exception as e:
        error_code = compute_error_code(e)
        logging.error(error_code, exc_info=True)
        try:
            log_fail_tuple(tuple_type, subtuple['key'], error_code)
        except LedgerError as e:
            logging.exception(e)


@app.task(bind=True, ignore_result=False)
def compute_task(self, tuple_type, subtuple, fltask):

    try:
        worker = self.request.hostname.split('@')[1]
        queue = self.request.delivery_info['routing_key']
    except Exception:
        worker = f"{settings.LEDGER['name']}.worker"
        queue = f"{settings.LEDGER['name']}"

    result = {'worker': worker, 'queue': queue, 'fltask': fltask}

    try:
        prepare_materials(subtuple, tuple_type)
        res = do_task(subtuple, tuple_type)
    except Exception as e:
        error_code = compute_error_code(e)
        logging.error(error_code, exc_info=True)

        try:
            log_fail_tuple(tuple_type, subtuple['key'], error_code)
        except LedgerError as e:
            logging.exception(e)

        return result

    try:
        log_success_tuple(tuple_type, subtuple['key'], res)
    except LedgerError as e:
        logging.exception(e)

    return result


def prepare_materials(subtuple, tuple_type):

    # get subtuple components
    objective = get_objective(subtuple)
    algo_content = get_algo(subtuple)
    if tuple_type == 'testtuple':
        model_content = get_model(subtuple)
    elif tuple_type == 'traintuple':
        models_content = get_models(subtuple)
    else:
        raise NotImplementedError()

    # create subtuple
    subtuple_directory = build_subtuple_folders(subtuple)
    put_opener(subtuple, subtuple_directory)
    put_data_sample(subtuple, subtuple_directory)
    put_metric(subtuple_directory, objective)
    put_algo(subtuple_directory, algo_content)
    if tuple_type == 'testtuple':
        put_model(subtuple, subtuple_directory, model_content)
    elif tuple_type == 'traintuple' and models_content:
        put_models(subtuple, subtuple_directory, models_content)

    logging.info(f'Prepare materials for {tuple_type} task: success ')


def do_task(subtuple, tuple_type):
    subtuple_directory = path.join(getattr(settings, 'MEDIA_ROOT'), 'subtuple', subtuple['key'])
    org_name = getattr(settings, 'ORG_NAME')

    # Federated learning variables
    fltask = None
    flrank = None

    if 'fltask' in subtuple and subtuple['fltask']:
        fltask = subtuple['fltask']
        flrank = int(subtuple['rank'])

    client = docker.from_env()

    try:
        result = _do_task(
            client,
            subtuple_directory,
            tuple_type,
            subtuple,
            fltask,
            flrank,
            org_name
        )
    except Exception as e:
        # If an exception is thrown set flrank == -1 (we stop the fl training)
        if fltask is not None:
            flrank = -1
        raise e
    finally:
        # Clean subtuple materials
        remove_subtuple_materials(subtuple_directory)

        # Rank == -1 -> Last fl subtuple or fl throws an exception
        if flrank == -1:
            flvolume = f'local-{fltask}-{org_name}'
            local_volume = client.volumes.get(volume_id=flvolume)
            try:
                local_volume.remove(force=True)
            except Exception:
                logging.error(f'Cannot remove local volume {flvolume}', exc_info=True)

    return result


def _do_task(client, subtuple_directory, tuple_type, subtuple, fltask, flrank, org_name):
    # Job log
    job_task_log = ''

    # subtuple setup
    model_path = path.join(subtuple_directory, 'model')
    data_path = path.join(subtuple_directory, 'data')

    ##########################################
    # RESOLVE SYMLINKS
    # TO DO:
    #   - Verify that real paths are safe
    #   - Try to see if it's clean to do that
    ##########################################
    symlinks_volume = {}
    for subfolder in os.listdir(data_path):
        real_path = os.path.realpath(os.path.join(data_path, subfolder))
        symlinks_volume[real_path] = {'bind': f'{real_path}', 'mode': 'ro'}

    ##########################################

    pred_path = path.join(subtuple_directory, 'pred')
    opener_file = path.join(subtuple_directory, 'opener/opener.py')
    metrics_file = path.join(subtuple_directory, 'metrics/metrics.py')
    volumes = {data_path: {'bind': '/sandbox/data', 'mode': 'ro'},
               pred_path: {'bind': '/sandbox/pred', 'mode': 'rw'},
               metrics_file: {'bind': '/sandbox/metrics/__init__.py', 'mode': 'ro'},
               opener_file: {'bind': '/sandbox/opener/__init__.py', 'mode': 'ro'}}

    # compute algo task
    algo_path = path.join(subtuple_directory)
    algo_docker = f'algo_{tuple_type}'.lower()  # tag must be lowercase for docker
    algo_docker_name = f'{algo_docker}_{subtuple["key"]}'
    model_volume = {model_path: {'bind': '/sandbox/model', 'mode': 'rw'}}

    if fltask is not None and flrank != -1:
        remove_image = False
    else:
        remove_image = True

    # create the command option for algo
    if tuple_type == 'traintuple':
        algo_command = 'train'    # main command

        # add list of inmodels
        if subtuple['inModels'] is not None:
            inmodels = [subtuple_model["traintupleKey"] for subtuple_model in subtuple['inModels']]
            algo_command = f"{algo_command} {' '.join(inmodels)}"

        # add fltask rank for training
        if flrank is not None:
            algo_command = f"{algo_command} --rank {flrank}"

    elif tuple_type == 'testtuple':
        algo_command = 'predict'    # main command

        inmodels = subtuple['model']["traintupleKey"]
        algo_command = f'{algo_command} {inmodels}'

    # local volume for fltask
    if fltask is not None and tuple_type == 'traintuple':
        flvolume = f'local-{fltask}-{org_name}'
        if flrank == 0:
            client.volumes.create(name=flvolume)
        else:
            client.volumes.get(volume_id=flvolume)

        model_volume[flvolume] = {'bind': '/sandbox/local', 'mode': 'rw'}

    job_task_log = compute_docker(
        client=client,
        resources_manager=resources_manager,
        dockerfile_path=algo_path,
        image_name=algo_docker,
        container_name=algo_docker_name,
        volumes={**volumes, **model_volume, **symlinks_volume},
        command=algo_command,
        remove_image=remove_image
    )

    # save model in database
    if tuple_type == 'traintuple':
        from substrapp.models import Model
        end_model_path = path.join(subtuple_directory, 'model/model')
        end_model_file_hash = get_hash(end_model_path, subtuple['key'])
        instance = Model.objects.create(pkhash=end_model_file_hash, validated=True)

        with open(end_model_path, 'rb') as f:
            instance.file.save('model', f)
        current_site = getattr(settings, "DEFAULT_DOMAIN")
        end_model_file = f'{current_site}{reverse("substrapp:model-file", args=[end_model_file_hash])}'

    # compute metric task
    metrics_path = path.join(getattr(settings, 'PROJECT_ROOT'), 'containers/metrics')   # comes with substrabac
    metrics_docker = f'metrics_{tuple_type}'.lower()  # tag must be lowercase for docker
    metrics_docker_name = f'{metrics_docker}_{subtuple["key"]}'
    compute_docker(
        client=client,
        resources_manager=resources_manager,
        dockerfile_path=metrics_path,
        image_name=metrics_docker,
        container_name=metrics_docker_name,
        volumes={**volumes, **symlinks_volume},
        command=None,
        remove_image=remove_image
    )

    # load performance
    with open(path.join(pred_path, 'perf.json'), 'r') as perf_file:
        perf = json.load(perf_file)

    global_perf = perf['all']

    result = {'global_perf': global_perf,
              'job_task_log': job_task_log}

    if tuple_type == 'traintuple':
        result['end_model_file_hash'] = end_model_file_hash
        result['end_model_file'] = end_model_file

    return result
