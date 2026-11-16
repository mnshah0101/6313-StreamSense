import pytest

from streamsense.data import taxonomy as tx


@pytest.fixture
def tax(make_cfg) -> tx.Taxonomy:
    return tx.Taxonomy.from_config(make_cfg().taxonomy)


def test_split_normalizes_case_space_and_aliases(tax):
    assert tx.split_terms(" Blurry , LENS-FLARE,,blur ", tax) == ("blur", "lens flare")
    assert tx.split_terms("compression_artifacts, stitching  artifact", tax) == (
        "compression artifacts",
        "stitching artifacts",
    )
    assert tx.split_terms("", tax) == ()
    assert tx.split_terms(None, tax) == ()


@pytest.mark.parametrize(
    ("term", "crew"),
    [
        ("blur", "blur_lens_smear"),
        ("glare", "overexposure"),
        ("lens flare", "overexposure"),
        ("no lights", "low_light"),
        ("stitching artifacts", "stitching_black_patch"),
        ("miscalibration", "miscalibration"),
        ("fog", "weather"),
        ("low contrast", "other"),
        ("never seen before", "other"),
    ],
)
def test_crew_mapping(tax, term, crew):
    assert tx.crew_class(term, tax) == crew


def test_weather_flag(tax):
    assert tx.weather_related(("haze", "blur"), tax)
    assert not tx.weather_related(("blur",), tax)


def test_unmapped_terms_are_counted(tax):
    assert tx.unmapped_terms([("blur", "noise"), ("noise",), ()], tax) == {"noise": 2}


def test_vocabulary_is_fit_with_min_count_and_other(tax):
    rows = [("blur",)] * 5 + [("fog",)] * 4 + [("blur", "glare")]
    vocab = tx.fit_vocabulary(rows, tax)
    assert vocab == ("blur", "other")
    assert tx.fold_terms(("fog", "blur", "glare"), vocab, tax) == ("blur", "other")
