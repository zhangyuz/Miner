my_dir=$(realpath $(dirname $0))
cur_dur=$(pwd)
cd $my_dir

export PYTHONPATH="$my_dir/..:$my_dir/../../Detonator:$PYTHONPATH"


if [ "$#" -ne 0 ]; then
  python -m unittest -v "$@"
else
  python -m unittest discover -v -c
fi

cd "$cur_dur"
