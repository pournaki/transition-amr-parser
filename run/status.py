import sys
import shutil
from time import sleep
import numpy as np
from glob import glob
import signal
import re
import os
from datetime import datetime
import argparse
from collections import defaultdict
from statistics import mean
from transition_amr_parser.io import read_config_variables, clbar


# Sanity check python3
if int(sys.version[0]) < 3:
    print("Needs at least Python 3")
    exit(1)


# results file content regex
smatch_results_re = re.compile(r'^F-score: ([0-9\.]+)')
checkpoint_re = re.compile(r'.*checkpoint([0-9]+)\.pt$')


def argument_parser():
    parser = argparse.ArgumentParser(description='Tool to check experiments')
    parser.add_argument(
        "--test",
        help="Show test results (if available)",
        action='store_true',
    )
    parser.add_argument(
        "--results",
        help="print results for all complete models",
        action='store_true',
    )
    parser.add_argument(
        "--long-results",
        help="print results for all complete models, with more info",
        action='store_true',
    )
    parser.add_argument(
        "-c", "--config",
        help="select one experiment by a config",
        type=str,
    )
    parser.add_argument(
        "--seed",
        help="optional seed of the experiment",
        type=str,
    )
    parser.add_argument(
        "--seed-average",
        help="Average numbers over seeds",
        action='store_true'
    )
    parser.add_argument(
        "--nbest",
        help="Top-n best checkpoints to keep",
        default=5
    )
    parser.add_argument(
        "--link-best",
        help="Link best model if all checkpoints are done",
        action='store_true'
    )
    parser.add_argument(
        "--remove",
        help="Remove checkpoints that have been evaluated and are not best "
             "checkpoints",
        action='store_true'
    )
    parser.add_argument(
        "--list-checkpoints-to-eval",
        help="return all checkpoints with pending evaluation for a seed",
        action='store_true'
    )
    parser.add_argument(
        "--list-checkpoints-ready-to-eval",
        help="return all existing checkpoints with pending evaluation for a"
             " seed",
        action='store_true'
    )
    parser.add_argument(
        "--wait-checkpoint-ready-to-eval",
        help="Wait 10 seconds to check if there is a checkpoint pending to "
             "eval, return path if it exists.",
        action='store_true'
    )
    parser.add_argument(
        "--clear",
        help="Clear screen before printing status",
        action='store_true'
    )
    args = parser.parse_args()
    return args


def check_model_training(seed_folder, max_epoch):

    diplay_lines = []
    final_checkpoint = f'{seed_folder}/checkpoint{max_epoch}.pt'
    if os.path.isfile(final_checkpoint):
        # Last epoch completed
        diplay_lines.append(
            (f"\033[92m{max_epoch}/{max_epoch}\033[0m", f"{seed_folder}")
        )
    else:
        # Get which epochs are completed
        epochs = []
        for checkpoint in glob(f'{seed_folder}/checkpoint*.pt'):
            fetch = checkpoint_re.match(checkpoint)
            if fetch:
                epochs.append(int(fetch.groups()[0]))
        if epochs:
            curr_epoch = max(epochs)
            diplay_lines.append(
                (f"\033[93m{curr_epoch}/{max_epoch}\033[0m", f"{seed_folder}")
            )
        else:
            curr_epoch = 0
            diplay_lines.append(
                (f"{curr_epoch}/{max_epoch}", f"{seed_folder}")
            )

    return diplay_lines


def read_results(seed_folder, eval_metric, target_epochs):

    val_result_re = re.compile(r'.*de[cv]-checkpoint([0-9]+)\.' + eval_metric)
    validation_folder = f'{seed_folder}/epoch_tests/'
    epochs = []
    for result in glob(f'{validation_folder}/*.{eval_metric}'):
        fetch = val_result_re.match(result)
        if fetch:
            epochs.append(int(fetch.groups()[0]))
    missing_epochs = set(target_epochs) - set(epochs)
    missing_epochs = sorted(missing_epochs, reverse=True)

    return target_epochs, missing_epochs


def get_checkpoints_to_eval(config_env_vars, seed, ready=False):
    """
    List absolute paths of checkpoints needed for evaluation. Restrict to
    existing ones if read=True
    """

    # Get variables from config
    model_folder = config_env_vars['MODEL_FOLDER']
    seed_folder = f'{model_folder}-seed{seed}'
    max_epoch = int(config_env_vars['MAX_EPOCH'])
    eval_metric = config_env_vars['EVAL_METRIC']
    eval_init_epoch = int(config_env_vars['EVAL_INIT_EPOCH'])

    # read results
    target_epochs = list(range(eval_init_epoch, max_epoch+1))
    target_epochs, missing_epochs = read_results(
        seed_folder, eval_metric, target_epochs
    )

    # construct paths
    checkpoints = []
    epochs = []
    for epoch in missing_epochs:
        checkpoint = f'{seed_folder}/checkpoint{epoch}.pt'
        if os.path.isfile(checkpoint) or not ready:
            checkpoints.append(os.path.realpath(checkpoint))
            epochs.append(epoch)

    return checkpoints, target_epochs, missing_epochs


def print_status(config_env_vars, seed, do_clear=False):

    # Inform about completed stages
    # pre-training ones
    status_lines = []
    for variable in ['ALIGNED_FOLDER', 'ORACLE_FOLDER', 'EMB_FOLDER',
                     'DATA_FOLDER']:
        step_folder = config_env_vars[variable]
        if os.path.isfile(f'{step_folder}/.done'):
            status_lines.append((f"\033[92mdone\033[0m", f"{step_folder}"))
        elif os.path.isdir(step_folder):
            status_lines.append((f"\033[93mpart\033[0m", f"{step_folder}"))
        else:
            status_lines.append((f"pend", f"{step_folder}"))

    # training/eval ones
    model_folder = config_env_vars['MODEL_FOLDER']
    if seed is None:
        seeds = config_env_vars['SEEDS'].split()
    else:
        assert seed in config_env_vars['SEEDS'].split(), \
            "{seed} is not a trained seed for the model"
        seeds = [seed]
    # loop over each model with a different random seed
    for seed in seeds:

        # all checkpoints trained
        seed_folder = f'{model_folder}-seed{seed}'
        max_epoch = int(config_env_vars['MAX_EPOCH'])
        status_lines.extend(check_model_training(seed_folder, max_epoch))

        # all checkpoints evaluated
        checkpoints, target_epochs, _ = \
            get_checkpoints_to_eval(config_env_vars, seed)
        if checkpoints:
            delta = len(target_epochs) - len(checkpoints)
            if delta > 0:
                status_lines.append((
                    f"\033[93m{delta}/{len(target_epochs)}\033[0m",
                    f"{seed_folder}"
                ))
            else:
                status_lines.append((
                    f"{delta}/{len(target_epochs)}",
                    f"{seed_folder}"
                ))

        else:
            status_lines.append((
                f"\033[92m{len(target_epochs)}/{len(target_epochs)}\033[0m",
                f"{seed_folder}"
            ))

        # Final model and results
        dec_checkpoint = config_env_vars['DECODING_CHECKPOINT']
        dec_checkpoint = f'{model_folder}-seed{seed}/{dec_checkpoint}'
        if os.path.isfile(dec_checkpoint):
            status_lines.append((f"\033[92mdone\033[0m", f"{dec_checkpoint}"))
        else:
            status_lines.append((f"pend", f"{dec_checkpoint}"))

    # format lines to avoid overflowing command line size
    ncol, _ = shutil.get_terminal_size((80, 20))
    col1_width = max(len_print(x[0]) for x in status_lines) + 2
    new_statues_lines = []
    for (col1, col2) in status_lines:
        delta = col1_width + 2 + len(col2) - ncol
        # correction for scape symbols
        delta_cl = len(col1) - len_print(col1)
        if delta_cl > 0:
            width = col1_width + delta_cl
        else:
            width = col1_width

        if delta > 0:
            half_delta = delta // 2 + 4
            half_col2 = len(col2) // 2
            col2_crop = col2[:half_col2 - half_delta]
            col2_crop += ' ... '
            col2_crop += col2[half_col2 + half_delta:]
            new_statues_lines.append(f'[{col1:^{width}}] {col2_crop}')
        else:
            new_statues_lines.append(f'[{col1:^{width}}] {col2}')

    # print
    if do_clear:
        os.system('clear')
    print('\n'.join(new_statues_lines))
    print()


def get_score_from_log(file_path, score_name):

    results = [None]

    if 'smatch' in score_name:
        regex = smatch_results_re
    else:
        raise Exception(f'Unknown score type {score_name}')

    with open(file_path) as fid:
        for line in fid:
            if regex.match(line):
                results = regex.match(line).groups()
                results = [100*float(x) for x in results]
                break

    return results


def get_best_checkpoints(config_env_vars, seed, target_epochs, n_best=5):
    model_folder = config_env_vars['MODEL_FOLDER']
    seed_folder = f'{model_folder}-seed{seed}'
    validation_folder = f'{seed_folder}/epoch_tests/'
    eval_metric = config_env_vars['EVAL_METRIC']
    scores = []
    missing_epochs = []
    rest_checkpoints = []

    for epoch in range(int(config_env_vars['MAX_EPOCH'])):

        # store paths of checkpoint that wont need to be evaluated for deletion
        checkpoint_file = f'{seed_folder}/checkpoint{epoch}.pt'
        if epoch not in target_epochs:
            if os.path.isfile(checkpoint_file):
                rest_checkpoints.append(checkpoint_file)
            else:
                continue

        results_file = \
            f'{validation_folder}/dec-checkpoint{epoch}.{eval_metric}'
        if not os.path.isfile(results_file):
            missing_epochs.append(epoch)
            continue
        score = get_score_from_log(results_file, eval_metric)
        if score == [None]:
            continue
        # TODO: Support other scores
        scores.append((score[0], epoch))

    sorted_scores = sorted(scores, key=lambda x: x[0])
    best_n_epochs = sorted_scores[-n_best:]
    rest_epochs = sorted_scores[:-n_best]

    best_n_checkpoints = [f'checkpoint{n}.pt' for _, n in best_n_epochs]
    if sorted_scores:
        rest_checkpoints += sorted([
            f'{seed_folder}/checkpoint{n}.pt' for _, n in rest_epochs
        ])
    else:
        # did not start yet to score any model, better keep last checkpoint.
        # not that we delete it midway through a copy to last_checkpoint.pt
        rest_checkpoints = rest_checkpoints[:-1]

    best_scores = [s for s, n in best_n_epochs]

    return (
        best_n_checkpoints, best_scores, rest_checkpoints, missing_epochs,
        sorted_scores
    )


def link_best_model(best_n_checkpoints, config_env_vars, seed, nbest):

    # link best model
    model_folder = config_env_vars['MODEL_FOLDER']
    eval_metric = config_env_vars['EVAL_METRIC']
    for n, checkpoint in enumerate(best_n_checkpoints):

        target_best = (f'{model_folder}-seed{seed}/'
                       f'checkpoint_{eval_metric}_best{nbest-n}.pt')
        source_best = checkpoint

        # get current best model (if exists)
        if os.path.islink(target_best):
            current_best = os.path.basename(os.path.realpath(target_best))
        else:
            current_best = None

        # replace link/checkpoint or create a new one
        if os.path.islink(target_best) and current_best != source_best:
            # We created a link before to a worse model, remove it
            os.remove(target_best)
        elif os.path.isfile(target_best):
            # If we ran remove_checkpoints.sh, we replaced the original
            # link by copy of the checkpoint. We dont know if this is the
            # correct checkpoint already
            os.remove(target_best)

        if (
            not os.path.islink(target_best)
            and not os.path.isfile(target_best)
        ):
            os.symlink(source_best, target_best)


def get_average_time_between_write(files):

    timestamps = []
    for dfile in files:
        timestamps.append((
            os.path.basename(dfile),
            datetime.fromtimestamp(os.stat(dfile).st_mtime)
        ))
    timestamps = sorted(timestamps, key=lambda x: x[1])
    deltas = [
        (x[1] - y[1]).seconds / 60.
        for x, y in zip(timestamps[1:], timestamps[:-1])
    ]
    if len(deltas) < 5:
        return None
    else:
        return mean(deltas[2:-2])


def get_speed_statistics(seed_folder):

    files = []
    for checkpoint in glob(f'{seed_folder}/checkpoint*.pt'):
        if checkpoint_re.match(checkpoint):
            files.append(checkpoint)

    minutes_per_epoch = get_average_time_between_write(files)

    files = []
    for checkpoint in glob(f'{seed_folder}/epoch_tests/*.actions'):
        files.append(checkpoint)

    minutes_per_test = get_average_time_between_write(files)

    return minutes_per_epoch, minutes_per_test


def average_results(results, fields, average_fields, ignore_fields,
                    concatenate_fields):

    # collect
    result_by_seed = defaultdict(list)
    for result in results:
        key = result['model_folder']
        result_by_seed[key].append(result)

    # leave only averages
    averaged_results = []
    for seed, sresults in result_by_seed.items():
        average_result = {}
        for field in fields:
            # ignore everything after space
            field = field.split()[0]
            if field in average_fields:
                samples = [r[field] for r in sresults if r[field] is not None]
                if samples:
                    average_result[field] = np.mean(samples)
                    # Add standard deviation
                    average_result[f'{field}-std'] = np.std(samples)
                else:
                    average_result[field] = None

            elif field in ignore_fields:
                average_result[field] = ''
            elif field in concatenate_fields:
                average_result[field] = ','.join([r[field] for r in sresults])
            else:
                average_result[field] = sresults[0][field]
        averaged_results.append(average_result)

    return averaged_results


def display_results(models_folder, config, set_seed, seed_average, do_test,
                    longr=False, do_clear=False):

    # Table header
    results = []

    if config:
        target_config_env_vars = read_config_variables(config)

    for model_folder in glob(f'{models_folder}/*/*'):
        for seed_folder in glob(f'{model_folder}/*'):

            # if config given, identify it by seed
            if set_seed and f'seed{set_seed}' not in seed_folder:
                continue
            else:
                seed = re.match('.*-seed([0-9]+)', seed_folder).groups()[0]

            # Read config contents and seed
            config_env_vars = read_config_variables(f'{seed_folder}/config.sh')

            # if config given, identify by folder
            if (
                config
                and config_env_vars['MODEL_FOLDER']
                != target_config_env_vars['MODEL_FOLDER']
            ):
                continue

            # Get speed stats
            minutes_per_epoch, minutes_per_test = \
                get_speed_statistics(seed_folder)
            max_epoch = int(config_env_vars['MAX_EPOCH'])
            if minutes_per_epoch and minutes_per_epoch > 1:
                epoch_time = minutes_per_epoch/60.*max_epoch
            else:
                epoch_time = None
            if minutes_per_test and minutes_per_test > 1:
                test_time = minutes_per_test
            else:
                test_time = None

            # get experiments info
            _, target_epochs, _ = get_checkpoints_to_eval(
                config_env_vars,
                seed,
                ready=True
            )
            checkpoints, scores, _, missing_epochs, sorted_scores = \
                get_best_checkpoints(
                    config_env_vars, seed, target_epochs, n_best=5
                )
            if scores == []:
                continue

            best_checkpoint, best_score = sorted(
                zip(checkpoints, scores), key=lambda x: x[1]
            )[-1]
            max_epoch = config_env_vars['MAX_EPOCH']
            best_epoch = re.match(
                'checkpoint([0-9]+).pt', best_checkpoint
            ).groups()[0]

            # get top-5 beam result
            # TODO: More granularity here. We may want to add many different
            # metrics and sets
            eval_metric = config_env_vars['EVAL_METRIC']
            sset = 'valid'
            cname = 'checkpoint_wiki.smatch_top5-avg'
            results_file = \
                f'{seed_folder}/beam10/{sset}_{cname}.pt.{eval_metric}'
            if os.path.isfile(results_file):
                best_top5_beam10_score = get_score_from_log(results_file,
                                                            eval_metric)[0]
            else:
                best_top5_beam10_score = None

            # Append result
            results.append(dict(
                model_folder=model_folder,
                seed=seed,
                data=config_env_vars['TASK_TAG'],
                oracle=os.path.basename(config_env_vars['ORACLE_FOLDER'][:-1]),
                features=os.path.basename(config_env_vars['EMB_FOLDER']),
                model=config_env_vars['TASK'] + f':{seed}',
                best=f'{best_epoch}/{max_epoch}',
                dev=best_score,
                top5_beam10=best_top5_beam10_score,
                train=epoch_time,
                dec=test_time,
            ))

            if do_test:
                sset = 'test'
                cname = 'checkpoint_wiki.smatch_top5-avg'
                results_file = \
                    f'{seed_folder}/beam10/{sset}_{cname}.pt.{eval_metric}'
                if os.path.isfile(results_file):
                    best_top5_beam10_test = get_score_from_log(results_file,
                                                               eval_metric)[0]
                else:
                    best_top5_beam10_test = None
                results[-1]['(test)'] = best_top5_beam10_test

    if do_test:
        fields = [
            'data', 'oracle', 'features', 'model', 'best', 'dev',
            'top5_beam10', '(test)', 'train (h)', 'dec (m)'
        ]

    else:
        fields = [
            'data', 'oracle', 'features', 'model', 'best', 'dev',
            'top5_beam10', 'train (h)', 'dec (m)'
        ]

    # TODO: average over seeds
    if seed_average:
        average_fields = [
            'dev', 'top5_beam10', '(test)', 'train (h)', 'dec (m)'
        ]
        ignore_fields = ['best']
        concatenate_fields = ['seed']
        results = average_results(results, fields, average_fields,
                                  ignore_fields, concatenate_fields)

    # sort by last row
    sort_field = 'top5_beam10'

    def get_score(x):
        if x[sort_field] is None:
            return -1
        else:
            return float(x[sort_field])
    results = sorted(results, key=get_score)

    # print
    if results:
        assert all(field.split()[0] in results[0].keys() for field in fields)
        formatter = {
            5: '{:.1f}'.format,
            6: '{:.1f}'.format,
            7: '{:.1f}'.format,
            8: '{:.1f}'.format,
            9: '{:.1f}'.format
        }
        print_table(fields, results, formatter=formatter, do_clear=do_clear)

        if config and longr:
            # single model result display
            minc = .95 * min([x[0] for x in sorted_scores])
            sorted_scores = sorted(sorted_scores, key=lambda x: x[1])
            pairs = [(str(x), y) for (y, x) in sorted_scores]
            clbar(pairs, ylim=(minc, None), ncol=79, yform='{:.4f}'.format)
            print()


def len_print(string):
    if string is None:
        return 0
    else:
        bash_scape = re.compile(r'\x1b\[\d+m|\x1b\[0m')
        return len(bash_scape.sub('', string))


def get_cell_str(row, field, formatter):
    field2 = field.split()[0]
    cell = row[field2]
    if cell is None:
        cell = ''
    if formatter and cell != '':
        cell = formatter(cell)
    if f'{field2}-std' in row:
        std = row[f'{field2}-std']
        if formatter:
            std = formatter(std)
        cell = f'{cell} ({std})'

    return cell


def print_table(header, data, formatter, do_clear=False):

    # data structure checks

    # find largest elemend per column
    max_col_size = []
    for n, field in enumerate(header):
        row_lens = [len(field)]
        for row in data:
            cell = get_cell_str(row, field, formatter.get(n, None))
            row_lens.append(len_print(cell))
        max_col_size.append(max(row_lens))

    # format and print
    if do_clear:
        os.system('clear')
    print('')
    col_sep = ' '
    row_str = ['{:^{width}}'.format(h, width=max_col_size[n])
               for n, h in enumerate(header)]
    print(col_sep.join(row_str))
    for row in data:
        row_str = []
        for n, field in enumerate(header):
            cell = get_cell_str(row, field, formatter.get(n, None))
            row_str.append('{:^{width}}'.format(cell, width=max_col_size[n]))
        print(col_sep.join(row_str))
    print('')


def ordered_exit(signum, frame):
    print("\nStopped by user\n")
    exit(0)


def main(args):

    # set ordered exit
    signal.signal(signal.SIGINT, ordered_exit)
    signal.signal(signal.SIGTERM, ordered_exit)

    checkpoints = None
    if args.results or args.long_results:

        # results display and exit
        display_results('DATA/*/models/', args.config, args.seed,
                        args.seed_average, args.test,
                        longr=bool(args.long_results),
                        do_clear=args.clear)

    elif args.wait_checkpoint_ready_to_eval:

        # List checkpoints that need to be evaluated to complete training. If
        # ready=True list only those checkpoints that exist already
        assert args.seed, "Requires --seed"
        config_env_vars = read_config_variables(args.config)
        eval_init_epoch = int(config_env_vars['EVAL_INIT_EPOCH'])
        while True:

            checkpoints, target_epochs, missing = get_checkpoints_to_eval(
                config_env_vars,
                args.seed,
                ready=True
            )
            if missing == []:
                print('Checkpoint evaluation complete!')
                break
            elif checkpoints:
                break

            print_status(config_env_vars, args.seed, do_clear=args.clear)
            print(f'Waiting for checkpoint {eval_init_epoch}')
            sleep(10)

    elif args.list_checkpoints_ready_to_eval or args.list_checkpoints_to_eval:

        # List checkpoints that need to be evaluated to complete training. If
        # ready=True list only those checkpoints that exist already
        assert args.seed, "Requires --seed"
        config_env_vars = read_config_variables(args.config)
        checkpoints, target_epochs, _ = get_checkpoints_to_eval(
            config_env_vars,
            args.seed,
            ready=bool(args.list_checkpoints_ready_to_eval)
        )

        # print checkpoints to be
        for checkpoint in checkpoints:
            print(checkpoint)
            sys.stdout.flush()

    else:

        # print status for this config
        config_env_vars = read_config_variables(args.config)
        print_status(config_env_vars, args.seed, do_clear=args.clear)

    if args.link_best or args.remove:

        # List checkpoints that need to be evaluated to complete training. If
        # ready=True list only those checkpoints that exist already
        assert args.seed, "Requires --seed"
        if checkpoints is None:
            checkpoints, target_epochs, _ = get_checkpoints_to_eval(
                config_env_vars,
                args.seed,
                ready=bool(args.list_checkpoints_ready_to_eval)
            )

        assert args.seed, "Requires --seed"
        best_n, best_scores, rest_checkpoints, missing_epochs, _ = \
            get_best_checkpoints(config_env_vars, args.seed, target_epochs,
                                 n_best=args.nbest)

        # link best model if all results are done
        if missing_epochs == [] and args.link_best:
            link_best_model(best_n, config_env_vars, args.seed,
                            args.nbest)

        # remove checkpoints not among the n-best
        for checkpoint in rest_checkpoints:
            if os.path.isfile(checkpoint):
                if not (
                    bool(args.list_checkpoints_ready_to_eval) or
                    bool(args.list_checkpoints_to_eval)
                ):
                    print(f'rm {checkpoint}')
                os.remove(checkpoint)


if __name__ == '__main__':
    main(argument_parser())