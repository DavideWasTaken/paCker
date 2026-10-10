"""Real Chromium checks for the local packing viewer and reusable scene."""
import json
import os
from pathlib import Path
import threading
import unittest
from http.server import ThreadingHTTPServer

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path(os.environ.get('PACKER_TEST_ARTIFACTS', ROOT / '.tools/viewer-tests'))


@unittest.skipUnless(sync_playwright, 'Playwright is needed for the real-browser viewer tests')
class ViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        import sys
        sys.path.insert(0, str(ROOT))
        from serve import Handler
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader'])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.page = self.browser.new_page(viewport={'width': 1440, 'height': 900}, accept_downloads=True)
        self.page.goto(self.base)
        self.page.locator('#boxes').wait_for(state='visible')
        self.page.wait_for_function("document.querySelector('#message').textContent.includes('Layout ready.')")

    def tearDown(self):
        self.page.close()

    def test_camera_fit_contains_corners_at_varied_scales_and_aspects(self):
        cases = self.page.evaluate("""async () => {
          const THREE = await import('/vendor/three.module.js');
          const module = await import('/camera.js').catch(() => ({}));
          if (!module.fitPackingCamera) return null;
          const results=[];
          for (const scale of [.0001, 1, 1000000]) for (const aspect of [.2, 1, 4]) {
            const bounds=new THREE.Box3(new THREE.Vector3(0,0,0),new THREE.Vector3(8*scale,2*scale,scale));
            const camera=new THREE.PerspectiveCamera(38,aspect,.01,1e9);camera.up.set(0,0,1);
            module.fitPackingCamera(THREE,camera,bounds,new THREE.Vector3(.8,-1,.78));
            const points=[];
            for (const x of [bounds.min.x,bounds.max.x]) for (const y of [bounds.min.y,bounds.max.y]) for (const z of [bounds.min.z,bounds.max.z])
              points.push(new THREE.Vector3(x,y,z).project(camera).toArray());
            results.push(points);
          }
          return results;
        }""")
        self.assertIsNotNone(cases, 'A projected-extents camera fit is required')
        for points in cases:
            self.assertLessEqual(max(abs(p[i]) for p in points for i in (0,1)), .901)
            self.assertGreater(max(abs(p[i]) for p in points for i in (0,1)), .70)
            self.assertTrue(all(-1 <= p[2] <= 1 for p in points))

    def test_inspection_expansion_separates_dense_centers_and_restores_positions(self):
        positions = self.page.evaluate("""async () => {
          const module=await import('/packing-scene.js');
          if (!module.inspectionCenter) return null;
          const bin={width:100,length:100,height:100};
          return Array.from({length:11},(_,i)=>{
            const center=[50,50,4+i*8];
            return {center,expanded:module.inspectionCenter(center,bin,1),restored:module.inspectionCenter(center,bin,0)};
          });
        }""")
        self.assertIsNotNone(positions, 'Explosion must expand the original centers')
        for i, pose in enumerate(positions):
            self.assertEqual(pose['center'], pose['restored'])
            if i:
                self.assertGreater(pose['expanded'][2]-positions[i-1]['expanded'][2], 8)

    def test_custom_import_is_labelled_without_solving_again(self):
        request={'boxes':[{'id':'custom','width':10,'length':10,'height':10}],
                 'items':[{'id':'custom','width':2,'length':2,'height':2}]}
        result=self.page.request.post(self.base+'/api/pack',data=json.dumps(request),
                                      headers={'Content-Type':'application/json'}).json()
        calls=[]
        self.page.route('**/api/pack',lambda route: (calls.append(route.request.post_data),route.abort()))
        self.page.locator('#file').set_input_files({'name':'custom.json','mimeType':'application/json',
            'buffer':json.dumps({'request':request,'result':result}).encode()})
        self.page.wait_for_function("document.querySelector('.item')?.textContent.includes('custom')")
        self.assertEqual('Custom / imported',self.page.locator('#sample option:checked').inner_text())
        self.assertEqual([],calls)
        self.page.wait_for_function("document.querySelector('#association').textContent.startsWith('VERIFIED')")
        self.assertNotIn('Checking geometry',self.page.locator('#message').inner_text())

    def submit(self, request):
        self.page.locator('#data-panel').evaluate('(el) => el.open = true')
        self.page.locator('#request').fill(json.dumps(request))
        self.page.locator('#solve').click()
        self.page.wait_for_function("document.querySelector('#message').textContent.includes('Layout ready.') || document.querySelector('#message').textContent.includes('unplaced.')")

    def test_actual_mesh_vertices_match_shared_pose_fixtures(self):
        fixtures = json.loads((ROOT / 'tests/fixtures/poses3d.json').read_text())
        actual = self.page.evaluate("""async cases => {
          const THREE = await import('/vendor/three.module.js');
          const {createItemMesh} = await import('/packing-scene.js');
          return cases.map(({pose}) => {
            const m = createItemMesh(THREE, pose, 0x36a58a);
            m.updateMatrixWorld(true);
            const vertices=Array(8);
            const positions=m.geometry.getAttribute('position');
            for (let i=0;i<positions.count;i++) {
              const local=new THREE.Vector3().fromBufferAttribute(positions,i);
              const bit=(local.x>0?1:0)|(local.y>0?2:0)|(local.z>0?4:0);
              vertices[bit]=m.localToWorld(local).toArray();
            }
            return vertices;
          });
        }""", fixtures['poses'])
        for case, vertices in zip(fixtures['poses'], actual):
            for expected, observed in zip(case['vertices'], vertices):
                for a, b in zip(expected, observed):
                    self.assertAlmostEqual(a, b, delta=1e-8, msg=case['name'])
        ordinary = self.page.evaluate("""async () => {
          const THREE = await import('/vendor/three.module.js');
          const {itemPose} = await import('/pose.js');
          const {createItemMesh} = await import('/packing-scene.js');
          const pose=itemPose({width:2,length:4,height:6,x:10,y:20,z:5,angle:90},1);
          const mesh=createItemMesh(THREE,pose,0x36a58a);mesh.updateMatrixWorld(true);
          const positions=mesh.geometry.getAttribute('position');
          for (let i=0;i<positions.count;i++) {
            const local=new THREE.Vector3().fromBufferAttribute(positions,i);
            if(local.x<0&&local.y<0&&local.z<0) return mesh.localToWorld(local).toArray();
          }
          throw Error('The mesh is missing its negative corner');
        }""")
        for expected, observed in zip([12,19,5], ordinary):
            self.assertAlmostEqual(expected, observed, delta=1e-8)

    def test_default_overview_and_scene_number_labels(self):
        self.assertEqual(2, self.page.locator('.box-card').count())
        self.page.screenshot(path=str(ARTIFACTS / 'default-overview-desktop.png'), full_page=True)
        self.assertTrue(self.page.get_by_label('Default rotation').is_visible())
        self.assertEqual('2', self.page.locator('#packed').inner_text())
        self.assertFalse(self.page.locator('#padding-info').is_visible())
        self.page.locator('#support-mode').select_option('geometric')
        self.assertIn('padding supplied by user',self.page.locator('#padding-info').inner_text())
        labels = self.page.evaluate("""async () => {
          const THREE = await import('/vendor/three.module.js');
          const {buildPackingScene} = await import('/packing-scene.js');
          const result={schema_version:1,bins:[{width:10,length:10,height:10,items:[
            {id:'a',instance:0,width:2,length:2,height:2,x:2,y:2,z:0,angle:0},
            {id:'b',instance:0,width:2,length:2,height:2,x:6,y:2,z:0,angle:0}]}]};
          return buildPackingScene(THREE,result).items.map(i=>[i.label?.isSprite,i.label?.userData.number]);
        }""")
        self.assertEqual([[True,1],[True,2]],labels)
        rows = self.page.evaluate("""async () => {
          const THREE = await import('/vendor/three.module.js');
          const {buildPackingScene} = await import('/packing-scene.js');
          const bins=Array.from({length:6},()=>({width:10,length:10,height:10,items:[]}));
          return buildPackingScene(THREE,{bins}).boxes.map(b=>b.group.position.y);
        }""")
        self.assertGreater(len(set(rows)),1)

    def test_ordinary_and_import_export_request_association(self):
        request = {'boxes':[{'id':'box','width':180,'length':180,'height':30}],
                   'items':[{'id':'bar','width':220,'length':30,'height':20,'rotation':'flat','diagonal':True}]}
        self.submit(request)
        self.assertEqual('1', self.page.locator('#boxes').inner_text())
        self.assertEqual(1, self.page.locator('.box-card').count())
        self.page.wait_for_function("document.querySelector('#association').textContent.includes('VERIFIED')")
        self.page.locator('#data-panel').evaluate('(el) => el.open = true')
        self.page.locator('#request').fill('{}')
        with self.page.expect_download() as event:
            self.page.locator('#export').click()
        document = json.loads(Path(event.value.path()).read_text())
        self.assertEqual('bar', document['request']['items'][0]['id'])
        self.assertEqual('complete', document['result']['status'])
        self.page.locator('#file').set_input_files({'name':'layout.json','mimeType':'application/json',
                                                    'buffer':json.dumps(document).encode()})
        self.page.wait_for_function("document.querySelector('#association').textContent.includes('VERIFIED')")
        self.page.locator('#request').fill('{}')
        self.assertIn('result uses its saved request',self.page.locator('#association').inner_text())
        with self.page.expect_download() as event:
            self.page.locator('#export').click()
        reexported=json.loads(Path(event.value.path()).read_text())
        self.assertEqual(document['request'],reexported['request'])
        self.page.locator('#file').set_input_files({'name':'old.json','mimeType':'application/json',
                                                    'buffer':json.dumps(document['result']).encode()})
        self.assertIn('UNVERIFIED', self.page.locator('#association').inner_text())
        self.assertTrue(self.page.locator('#png').is_disabled())
        self.page.locator('#request-file').set_input_files({'name':'original.json','mimeType':'application/json',
                                                            'buffer':json.dumps(document['request']).encode()})
        self.page.wait_for_function("document.querySelector('#association').textContent.includes('VERIFIED')")
        self.assertTrue(self.page.locator('#png').is_enabled())

    def test_verified_browser_png_and_invalid_import(self):
        from test_render import png_dimensions
        self.page.wait_for_function("document.querySelector('#association').textContent.includes('VERIFIED')")
        self.page.locator('.box-card').nth(1).click()
        self.page.locator('#png-view').select_option('top')
        with self.page.expect_download() as event:
            self.page.locator('#png').click()
        png=Path(event.value.path()).read_bytes()
        self.assertEqual((1024,768),png_dimensions(png))
        self.assertIn('box-2-top',event.value.suggested_filename)
        import_document=json.loads(self.page.request.post(self.base+'/api/pack',
            data=json.dumps({'boxes':[{'id':'B','width':10,'length':10,'height':10}],
                             'items':[{'id':'I','width':2,'length':2,'height':2}]}),
            headers={'Content-Type':'application/json'}).text())
        import_document['bins'][0]['items'][0]['x']=100
        pair={'request':{'boxes':[{'id':'B','width':10,'length':10,'height':10}],
                         'items':[{'id':'I','width':2,'length':2,'height':2}]},'result':import_document}
        self.page.locator('#file').set_input_files({'name':'invalid.json','mimeType':'application/json',
                                                    'buffer':json.dumps(pair).encode()})
        self.page.wait_for_function("document.querySelector('#association').textContent.includes('UNVERIFIED')")
        self.assertTrue(self.page.locator('#png').is_disabled())

    def test_png_export_times_out_while_render_page_is_loading(self):
        self.page.wait_for_function("document.querySelector('#association').textContent.includes('VERIFIED')")
        self.page.route('**/render.html', lambda route: route.fulfill(
            content_type='text/html', body='<script type="module">await new Promise(()=>{})</script>'))
        self.page.locator('#png').click()
        self.page.wait_for_function("document.querySelector('#message').textContent.includes('Image renderer timed out.')",
                                    timeout=17000)
        self.assertTrue(self.page.locator('#png').is_enabled())
        self.assertEqual(0,self.page.locator('iframe').count())

    def test_imported_layout_wins_over_older_pending_calculation(self):
        old={'boxes':[{'id':'old-box','width':10,'length':10,'height':10}],
             'items':[{'id':'OLD','width':2,'length':2,'height':2}]}
        imported={'boxes':[{'id':'import-box','width':10,'length':10,'height':10}],
                  'items':[{'id':'IMPORTED','width':3,'length':3,'height':3}]}
        response=self.page.request.post(self.base+'/api/pack',data=json.dumps(imported),
                                        headers={'Content-Type':'application/json'})
        self.assertEqual(200,response.status)
        import_document={'request':imported,'result':response.json()}
        held=[]
        self.page.route('**/api/pack',lambda route: held.append(route))
        self.page.locator('#data-panel').evaluate('(el) => el.open = true')
        self.page.locator('#request').fill(json.dumps(old))
        self.page.locator('#solve').click()
        self.page.wait_for_function("document.querySelector('#message').textContent.includes('Calculating')")
        self.assertEqual(1,len(held))
        self.page.locator('#file').set_input_files({'name':'imported.json','mimeType':'application/json',
                                                    'buffer':json.dumps(import_document).encode()})
        self.page.locator('.item').filter(has_text='IMPORTED').first.wait_for()
        held[0].fulfill(status=200,content_type='application/json',body=json.dumps({'status':'complete',
            'bins':[{'id':'bin-1','type_id':'old-box','width':10,'length':10,'height':10,'items':[
                {'id':'OLD','instance':0,'width':2,'length':2,'height':2,'x':2,'y':2,'z':0,'angle':0}]}],
            'unpacked':[],'stats':{'utilization':.008,'elapsed_ms':1,'candidates':1,'box_count':1}}))
        self.page.wait_for_timeout(100)
        self.assertTrue(self.page.locator('#solve').is_enabled())
        self.assertIn('IMPORTED',self.page.locator('.item').first.inner_text())
        self.assertIn('IMPORTED',self.page.locator('#request').input_value())
        self.assertIn('imported',self.page.locator('#message').inner_text())
        with self.page.expect_download() as event:
            self.page.locator('#export').click()
        exported=json.loads(Path(event.value.path()).read_text())
        self.assertEqual('IMPORTED',exported['request']['items'][0]['id'])
        self.assertEqual('IMPORTED',exported['result']['bins'][0]['items'][0]['id'])

    def test_plain_editor_change_keeps_pending_submission_snapshot(self):
        old={'boxes':[{'id':'box','width':10,'length':10,'height':10}],
             'items':[{'id':'SUBMITTED','width':2,'length':2,'height':2}]}
        held=[]
        self.page.route('**/api/pack',lambda route: held.append(route))
        self.page.locator('#data-panel').evaluate('(el) => el.open = true')
        self.page.locator('#request').fill(json.dumps(old))
        self.page.locator('#solve').click()
        self.page.wait_for_function("document.querySelector('#message').textContent.includes('Calculating')")
        self.assertEqual(1,len(held))
        self.page.locator('#request').fill('{"items":[],"boxes":[]}')
        result=self.page.request.post(self.base+'/api/pack',data=json.dumps(old),
                                      headers={'Content-Type':'application/json'}).json()
        held[0].fulfill(status=200,content_type='application/json',body=json.dumps(result))
        self.page.wait_for_function("document.querySelector('.item')?.textContent.includes('SUBMITTED')")
        with self.page.expect_download() as event:
            self.page.locator('#export').click()
        exported=json.loads(Path(event.value.path()).read_text())
        self.assertEqual('SUBMITTED',exported['request']['items'][0]['id'])
        self.assertIn('result uses its saved request',self.page.locator('#association').inner_text())

    def test_new_sample_supersedes_pending_calculation(self):
        held=[]
        def hold_first(route):
            if held: route.continue_()
            else: held.append(route)
        self.page.route('**/api/pack',hold_first)
        self.page.locator('#data-panel').evaluate('(el) => el.open = true')
        self.page.locator('#request').fill(json.dumps({'boxes':[{'id':'old','width':10,'length':10,'height':10}],
                                                      'items':[{'id':'OLD','width':2,'length':2,'height':2}]}))
        self.page.locator('#solve').click()
        self.page.wait_for_function("document.querySelector('#message').textContent.includes('Calculating')")
        self.assertEqual(1,len(held))
        self.page.locator('#sample').select_option('rod')
        self.page.wait_for_function("document.querySelector('.item')?.textContent.includes('Rod')")
        held[0].fulfill(status=200,content_type='application/json',body=json.dumps({'status':'complete',
            'bins':[{'id':'bin-1','type_id':'old','width':10,'length':10,'height':10,'items':[
                {'id':'OLD','instance':0,'width':2,'length':2,'height':2,'x':2,'y':2,'z':0,'angle':0}]}],
            'unpacked':[],'stats':{'utilization':.008,'elapsed_ms':1,'candidates':1,'box_count':1}}))
        self.page.wait_for_timeout(100)
        self.assertIn('Rod',self.page.locator('.item').first.inner_text())
        self.assertTrue(self.page.locator('#solve').is_enabled())

    def test_default_rotation_only_fills_unspecified_items(self):
        self.page.locator('#rotation-default').select_option('none')
        self.page.locator('#solve').click()
        self.page.wait_for_function("document.querySelector('#message').textContent.includes('Layout ready.')")
        with self.page.expect_download() as event:
            self.page.locator('#export').click()
        saved=json.loads(Path(event.value.path()).read_text())
        self.assertEqual('none', saved['request']['items'][0]['rotation'])
        request={'boxes':[{'id':'b','width':10,'length':10,'height':10}],
                 'items':[{'id':'fixed','width':2,'length':2,'height':2,'rotation':'flat','diagonal':False}]}
        self.submit(request)
        with self.page.expect_download() as event:
            self.page.locator('#export').click()
        saved=json.loads(Path(event.value.path()).read_text())
        self.assertEqual('flat', saved['request']['items'][0]['rotation'])
        self.assertFalse(saved['request']['items'][0]['diagonal'])

    def test_drag_orbit_and_inspection_tools_change_rendered_canvas(self):
        canvas=self.page.locator('#canvas')
        before=canvas.screenshot()
        bounds=canvas.bounding_box()
        x=bounds['x']+bounds['width']*.55
        y=bounds['y']+bounds['height']*.5
        self.page.mouse.move(x,y)
        self.page.mouse.down()
        self.page.mouse.move(x+140,y+65,steps=8)
        self.page.mouse.up()
        self.page.wait_for_timeout(500)
        orbited=canvas.screenshot(path=str(ARTIFACTS / 'orbit-desktop.png'))
        self.assertNotEqual(before,orbited)
        self.page.locator('#faithful').uncheck()
        self.page.locator('#explode').evaluate("el => {el.value='100';el.dispatchEvent(new Event('input',{bubbles:true}));}")
        exploded=canvas.screenshot(path=str(ARTIFACTS / 'exploded-desktop.png'))
        self.assertNotEqual(orbited,exploded)
        self.page.locator('#step').evaluate("el => {el.value='1';el.dispatchEvent(new Event('input',{bubbles:true}));}")
        partial=canvas.screenshot(path=str(ARTIFACTS / 'inspection-step-desktop.png'))
        self.assertNotEqual(exploded,partial)
        self.page.locator('#faithful').check()
        self.assertEqual('2 / 2',self.page.locator('#step-value').inner_text())
        self.assertEqual('0%',self.page.locator('#explode-value').inner_text())
        canvas.screenshot(path=str(ARTIFACTS / 'faithful-restored-desktop.png'))

    def test_free3d_rod_and_faithful_preview(self):
        request = json.loads((ROOT / 'examples/free3d-rod.json').read_text())
        self.page.locator('#support-mode').select_option('geometric')
        self.submit(request)
        self.assertEqual('1', self.page.locator('#boxes').inner_text())
        self.assertIn('rod', self.page.locator('.item').first.inner_text())
        self.page.locator('.item').first.click()
        self.assertNotIn('Quaternion', self.page.locator('#selected-label').inner_text())
        self.assertIn('rod', self.page.locator('#selected-label').inner_text())
        self.page.locator('#selected-detail').evaluate('(el) => el.open = true')
        self.assertIn('Quaternion', self.page.locator('#selected-detail').inner_text())
        self.page.locator('#faithful').check()
        self.assertTrue(self.page.locator('#step').is_disabled())
        self.assertTrue(self.page.locator('#explode').is_disabled())
        self.assertEqual('0%', self.page.locator('#explode-value').inner_text())
        self.assertEqual('1 / 1', self.page.locator('#step-value').inner_text())
        self.page.locator('#data-panel').evaluate('(el) => el.open = false')
        self.page.screenshot(path=str(ARTIFACTS / 'free3d-rod-desktop.png'), full_page=True)

    def test_multibox_overview_and_partial_identities(self):
        request = {'boxes':[{'id':'one','width':10,'length':10,'height':10,'quantity':2}],
                   'items':[{'id':'cube','width':9,'length':9,'height':9,'quantity':2}]}
        self.submit(request)
        self.assertEqual('2', self.page.locator('#boxes').inner_text())
        self.assertEqual(2, self.page.locator('.box-card').count())
        self.page.locator('.box-card').nth(1).click()
        self.assertIn('Box 2', self.page.locator('#bin-info').inner_text())
        self.page.locator('#all-boxes').click()
        self.assertIn('All 2 boxes', self.page.locator('#bin-info').inner_text())
        self.page.locator('#data-panel').evaluate('(el) => el.open = false')
        self.page.screenshot(path=str(ARTIFACTS / 'multi-box-desktop.png'), full_page=True)
        request['boxes'][0]['quantity'] = 1
        self.submit(request)
        self.assertIn('cube #2', self.page.locator('#unpacked-items').inner_text())
        self.page.screenshot(path=str(ARTIFACTS / 'partial-desktop.png'), full_page=True)

    def test_xy_diagonal_and_mobile_layout(self):
        request = {'boxes':[{'id':'square','width':180,'length':180,'height':30}],
                   'items':[{'id':'diagonal bar','width':220,'length':30,'height':20,
                             'rotation':'flat','diagonal':True}]}
        self.submit(request)
        self.assertIn('diagonal bar', self.page.locator('.item').first.inner_text())
        self.page.locator('.item').first.click()
        self.assertIn('diagonal bar', self.page.locator('#selected-label').inner_text())
        self.page.locator('#selected-detail').evaluate('(el) => el.open = true')
        self.assertIn('Quaternion', self.page.locator('#selected-detail').inner_text())
        self.page.locator('#selected-detail').evaluate('(el) => el.open = false')
        self.page.locator('#data-panel').evaluate('(el) => el.open = false')
        self.page.screenshot(path=str(ARTIFACTS / 'xy-diagonal-desktop.png'), full_page=True)
        self.page.set_viewport_size({'width':390,'height':844})
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 391)
        self.assertTrue(self.page.locator('#solve').is_visible())
        self.assertTrue(self.page.locator('.box-card').first.is_visible())
        self.page.screenshot(path=str(ARTIFACTS / 'xy-diagonal-mobile.png'), full_page=True)


if __name__ == '__main__':
    unittest.main()
