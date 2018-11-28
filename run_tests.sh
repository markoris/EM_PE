python em_pe/tests/imports_test.py
python em_pe/tests/models_test.py

rm -rf em_pe/tests/Data/
mkdir em_pe/tests/Data/
python em_pe/tests/generate_test_data.py
python em_pe/generate_posterior_samples.py --dat em_pe/tests/Data/ -v --m one_band_test 1 --f test_bandA.txt --out em_pe/tests/Data/posterior_samples.txt
