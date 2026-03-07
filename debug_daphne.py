import sys

if __name__ == '__main__':
    # insert here whatever commands you use to run daphne
    sys.argv = ['daphne', ' root_files.asgi:application', '9002']
    from daphne.cli import CommandLineInterface

    CommandLineInterface.entrypoint()