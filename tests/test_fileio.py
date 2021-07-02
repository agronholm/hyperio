import os
import pathlib
import platform
from typing import Tuple

import pytest
from _pytest.tmpdir import TempPathFactory

from anyio import AsyncFile, Path, open_file

pytestmark = pytest.mark.anyio


class TestAsyncFile:
    @pytest.fixture(scope='class')
    def testdata(cls) -> bytes:
        return b''.join(bytes([i] * 1000) for i in range(10))

    @pytest.fixture
    def testdatafile(self, tmp_path_factory: TempPathFactory, testdata: bytes) -> pathlib.Path:
        file = tmp_path_factory.mktemp('file').joinpath('testdata')
        file.write_bytes(testdata)
        return file

    async def test_open_close(self, testdatafile: pathlib.Path) -> None:
        f = await open_file(testdatafile)
        await f.aclose()

    async def test_read(self, testdatafile: pathlib.Path, testdata: bytes) -> None:
        async with await open_file(testdatafile, 'rb') as f:
            data = await f.read()

        assert f.closed
        assert data == testdata

    async def test_write(self, testdatafile: pathlib.Path, testdata: bytes) -> None:
        async with await open_file(testdatafile, 'ab') as f:
            await f.write(b'f' * 1000)

        assert testdatafile.stat().st_size == len(testdata) + 1000

    async def test_async_iteration(self, tmp_path: pathlib.Path) -> None:
        lines = ['blah blah\n', 'foo foo\n', 'bar bar']
        testpath = tmp_path.joinpath('testfile')
        testpath.write_text(''.join(lines), 'ascii')
        async with await open_file(str(testpath)) as f:
            lines_i = iter(lines)
            async for line in f:
                assert line == next(lines_i)  # type: ignore[comparison-overlap]


class TestPath:
    @pytest.fixture
    def populated_tmpdir(self, tmp_path: pathlib.Path) -> pathlib.Path:
        tmp_path.joinpath('testfile').touch()
        tmp_path.joinpath('testfile2').touch()
        subdir = tmp_path / 'subdir'
        subdir.mkdir()
        subdir.joinpath('dummyfile1.txt').touch()
        subdir.joinpath('dummyfile2.txt').touch()
        return tmp_path

    async def test_properties(self) -> None:
        """Ensure that all public properties and methods are available on the async Path class."""
        path = pathlib.Path('/test/path/another/part')
        stdlib_properties = {p for p in dir(path) if p.startswith('__') or not p.startswith('_')}
        stdlib_properties.discard('link_to')
        stdlib_properties.discard('__class_getitem__')

        async_path = Path(path)
        anyio_properties = {p for p in dir(async_path)
                            if p.startswith('__') or not p.startswith('_')}

        missing = stdlib_properties - anyio_properties
        assert not missing

    def test_name_property(self) -> None:
        assert Path('/abc/xyz/foo.txt.zip').name == 'foo.txt.zip'

    def test_parent_property(self) -> None:
        parent = Path('/abc/xyz/foo.txt').parent
        assert isinstance(parent, Path)
        assert str(parent) == f'{os.path.sep}abc{os.path.sep}xyz'

    def test_parents_property(self) -> None:
        parents = Path('/abc/xyz/foo.txt').parents
        assert len(parents) == 3
        assert all(isinstance(parent, Path) for parent in parents)
        assert str(parents[0]) == f'{os.path.sep}abc{os.path.sep}xyz'
        assert str(parents[1]) == f'{os.path.sep}abc'
        assert str(parents[2]) == os.path.sep

    def test_stem_property(self) -> None:
        assert Path('/abc/xyz/foo.txt.zip').stem == 'foo.txt'

    def test_suffix_property(self) -> None:
        assert Path('/abc/xyz/foo.txt.zip').suffix == '.zip'

    def test_suffixes_property(self) -> None:
        assert Path('/abc/xyz/foo.tar.gz').suffixes == ['.tar', '.gz']

    @pytest.mark.parametrize('args, result', [
        (('/xyz', 'abc'), True),
        (('/xyz', 'baz'), False)
    ])
    def test_is_relative_to(self, args: Tuple[str], result: bool) -> None:
        assert Path('/xyz/abc/foo').is_relative_to(*args) == result

    async def test_glob(self, populated_tmpdir: pathlib.Path) -> None:
        all_paths = []
        async for path in Path(populated_tmpdir).glob('**/*.txt'):
            assert isinstance(path, Path)
            all_paths.append(path.name)

        all_paths.sort()
        assert all_paths == ['dummyfile1.txt', 'dummyfile2.txt']

    async def test_rglob(self, populated_tmpdir: pathlib.Path) -> None:
        all_paths = []
        async for path in Path(populated_tmpdir).rglob('*.txt'):
            assert isinstance(path, Path)
            all_paths.append(path.name)

        all_paths.sort()
        assert all_paths == ['dummyfile1.txt', 'dummyfile2.txt']

    async def test_iterdir(self, populated_tmpdir: pathlib.Path) -> None:
        all_paths = []
        async for path in Path(populated_tmpdir).iterdir():
            assert isinstance(path, Path)
            all_paths.append(path.name)

        all_paths.sort()
        assert all_paths == ['subdir', 'testfile', 'testfile2']

    def test_joinpath(self):
        path = Path('/foo').joinpath('bar')
        assert path == Path('/foo/bar')

    @pytest.mark.skipif(platform.system() == 'Windows',
                        reason='chmod() is not available on Windows')
    async def test_chmod(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'testfile'
        path.touch(0o666)
        await Path(path).chmod(0o444)
        assert path.stat().st_mode & 0o777 == 0o444

    @pytest.mark.skipif(not hasattr(os, 'lchmod'), reason='os.lchmod() is not available')
    async def test_lchmod(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'testfile'
        path.symlink_to('/foo/bar/baz')
        await Path(path).lchmod(0o600)
        assert path.lstat().st_mode & 0o777 == 0o600

    @pytest.mark.skipif(platform.system() == 'Windows',
                        reason='symbolic links are not supported on Windows')
    async def test_lstat(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path.joinpath('testfile')
        path.symlink_to('/foo/bar/baz')
        result = await Path(path).lstat()
        assert isinstance(result, os.stat_result)

    @pytest.mark.skipif(platform.system() == 'Windows',
                        reason='owner and group are not supported on Windows')
    async def test_group(self, tmp_path: pathlib.Path) -> None:
        import grp
        group_name = grp.getgrgid(os.getegid()).gr_name
        assert await Path(tmp_path).group() == group_name

    async def test_mkdir(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'testdir'
        await Path(path).mkdir()
        assert path.is_dir()

    async def test_open(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'testfile'
        path.write_bytes(b'bibbitibobbitiboo')
        fp = await Path(path).open('rb')
        assert isinstance(fp, AsyncFile)
        assert fp.name == str(path)
        await fp.aclose()

    @pytest.mark.skipif(platform.system() == 'Windows',
                        reason='owner and group are not supported on Windows')
    async def test_owner(self, tmp_path: pathlib.Path) -> None:
        import pwd
        user_name = pwd.getpwuid(os.geteuid()).pw_name
        assert await Path(tmp_path).owner() == user_name

    @pytest.mark.skipif(platform.system() == 'Windows',
                        reason='symbolic links are not supported on Windows')
    async def test_readlink(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path.joinpath('testfile')
        path.symlink_to('/foo/bar/baz')
        link_target = await Path(path).readlink()
        assert isinstance(link_target, Path)
        assert str(link_target) == '/foo/bar/baz'

    async def test_read_bytes(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'testfile'
        path.write_bytes(b'bibbitibobbitiboo')
        assert await Path(path).read_bytes() == b'bibbitibobbitiboo'

    async def test_read_text(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'testfile'
        path.write_text('some text åäö', encoding='utf-8')
        assert await Path(path).read_text(encoding='utf-8') == 'some text åäö'

    async def test_rename(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'somefile'
        path.touch()
        target = tmp_path / 'anotherfile'
        result = await Path(path).rename(Path(target))
        assert isinstance(result, Path)
        assert result == target

    async def test_replace(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'somefile'
        path.write_text('hello')
        target = tmp_path / 'anotherfile'
        target.write_text('world')
        result = await Path(path).replace(Path(target))
        assert isinstance(result, Path)
        assert result == target
        assert target.read_text() == 'hello'

    async def test_resolve(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'somedir' / '..' / 'somefile'
        result = await Path(path).resolve()
        assert result == tmp_path / 'somefile'

    async def test_rmdir(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'somedir'
        path.mkdir()
        await Path(path).rmdir()
        assert not path.exists()

    async def test_samefile(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'somefile'
        path.touch()
        assert await Path(tmp_path / 'somefile').samefile(Path(path))

    async def test_stat(self, tmp_path: pathlib.Path) -> None:
        result = await Path(tmp_path).stat()
        assert isinstance(result, os.stat_result)

    async def test_touch(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'testfile'
        await Path(path).touch()
        assert path.is_file()

    @pytest.mark.skipif(platform.system() == 'Windows',
                        reason='symbolic links are not supported on Windows')
    async def test_symlink_to(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'testfile'
        target = tmp_path / 'link'
        await Path(path).symlink_to(Path(target))
        assert path.is_symlink()

    async def test_unlink(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'testfile'
        path.touch()
        await Path(path).unlink()
        assert not path.exists()

    async def test_unlink_missing_file(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'testfile'
        await Path(path).unlink(missing_ok=True)
        with pytest.raises(FileNotFoundError):
            await Path(path).unlink(missing_ok=False)

    def test_with_name(self) -> None:
        assert Path('/xyz/foo.txt').with_name('bar').name == 'bar'

    def test_with_stem(self) -> None:
        assert Path('/xyz/foo.txt').with_stem('bar').name == 'bar.txt'

    def test_with_suffix(self) -> None:
        assert Path('/xyz/foo.txt.gz').with_suffix('.zip').name == 'foo.txt.zip'

    async def test_write_bytes(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'testfile'
        await Path(path).write_bytes(b'bibbitibobbitiboo')
        assert path.read_bytes() == b'bibbitibobbitiboo'

    async def test_write_text(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'testfile'
        await Path(path).write_text('some text åäö', encoding='utf-8')
        assert path.read_text(encoding='utf-8') == 'some text åäö'
